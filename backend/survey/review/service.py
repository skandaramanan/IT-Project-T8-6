"""Review policy independent of HTTP. Every decision is embedded in JSONL."""

import csv
import json
from collections import Counter
from copy import deepcopy
from dataclasses import replace
from datetime import UTC, datetime
from uuid import uuid4

from survey.extraction.card_fields import (
    FIELD_SCHEMA,
    SURVEY_FRONT_DWELLING_FIELDS,
)
from survey.extraction.code_book import CLOSED_CATEGORIES, SENTINEL_CODES, decode
from survey.extraction.record import (
    SCHEMA_VERSION,
    build_record_id,
    review_schema_version,
)
from survey.records import (
    RecordStore,
    Reference,
    ReviewError,
    current_fields,
    digest,
    physical_card_id,
    resolve_field,
)
from survey.review.fields import field_pointers
from survey.review.scans import ScanSource

FIELD_POSITIONS = {field.name: index for index, field in enumerate(FIELD_SCHEMA)}


def printed_column(label: str) -> str:
    position = FIELD_POSITIONS[label]
    if position < FIELD_POSITIONS["Normal Household I."]:
        return "Left column"
    if position < FIELD_POSITIONS["Length of Residence"]:
        return "Middle column"
    return "Right column"


def state(field: dict) -> str:
    return field.get("review", {}).get("state", "pending")


def snapshot(field: dict) -> dict:
    return deepcopy({k: v for k, v in field.items() if k != "review"})


def credentials(reviewer, request_id):
    name = reviewer.strip()
    if not name or len(name) > 100:
        raise ReviewError(
            "invalid_reviewer", "Enter a reviewer name (1–100 characters)"
        )
    if not request_id or len(request_id) > 128:
        raise ReviewError(
            "invalid_request_id", "Supply a request ID (1–128 characters)"
        )
    return name


def field_after(field, spec, action, value):
    """The field's values after one non-undo decision; history is the caller's."""
    after = snapshot(field)
    if action == "correct":
        if not spec.valid_correction(value):
            raise ReviewError(
                "invalid_value",
                "Enter 1–4 ASCII digits with an optional letter"
                if spec.identity_kind == "dwelling" or spec.front_dwelling_number
                else "Enter 1–2 ASCII digits; zeros are preserved"
                if spec.identity_kind
                else "Enter nonblank text exactly as written"
                if spec.spec.kind == "text"
                else "Enter 1–64 ASCII digits; zeros are preserved",
            )
        category = spec.spec.code_book_category
        coded = category in CLOSED_CATEGORIES or category in SENTINEL_CODES
        after.update(
            value=value,
            status="ok",
            code=value if coded else None,
            label=decode(category, value) if coded else None,
        )
    elif action in {"no_data", "illegible"}:
        after.update(value=None, status=action, code=None, label=None)
    elif action != "accept":
        raise ReviewError("unsupported_action", "Unsupported field action")
    if action != "accept":
        after.setdefault("original_value", field.get("original_value", field["value"]))
        after["origin"] = "corrected"
    return after


def active_decisions(history: list[dict]) -> list[dict]:
    active = []
    for event in history:
        if event["action"] == "undo":
            if not active or active[-1]["id"] != event["undo_target"]:
                raise ReviewError(
                    "invalid_history", "Undo history is not in latest-decision order"
                )
            active.pop()
        else:
            active.append(event)
    return active


def identity_municipality(dwelling, household, index):
    """Retain each legacy card's municipality evidence from its stored ID."""
    if "municipality" in household:
        return household["municipality"].get("value")
    if household.get("record_id"):
        return household["record_id"].split("-")[0]
    if index and "municipality_mismatch" in dwelling.get("flags", []):
        return None
    return dwelling["municipality"].get("value")


def identity_note_topology(record):
    dwelling = record["dwelling"]
    return [
        {
            "image": next(
                (
                    card["image"]
                    for card in dwelling.get("cards", [])
                    if card["role"] == "survey-front"
                    and card.get("page") == note.get("front_page")
                ),
                None,
            ),
            "front_page": note.get("front_page"),
            "page": note.get("page"),
        }
        for note in dwelling.get("notes", [])
    ]


def identity_ids(record, municipality_overrides=None):
    """Derive coding IDs without changing physical ownership or associations."""
    dwelling = record["dwelling"]
    ids = []
    for index, household in enumerate(dwelling["households"]):
        try:
            ids.append(
                build_record_id(
                    (municipality_overrides or {}).get(
                        index, identity_municipality(dwelling, household, index)
                    )
                    or "",
                    household.get("dwelling_no", dwelling.get("dwelling_no", {})).get(
                        "value"
                    )
                    or "",
                    household["household_no"].get("value") or "",
                )
            )
        except ValueError:
            ids.append(None)
    return ids


def identity_issues(record, identity_counts):
    dwelling = record["dwelling"]
    ids = identity_ids(record)
    issues = []
    if any(identity is None for identity in ids) or any(
        household.get("record_id") is None for household in dwelling["households"]
    ):
        issues.append(
            {
                "code": "incomplete_identity",
                "message": "Some coding identity values are missing or invalid.",
            }
        )
    if any(identity is not None and identity_counts[identity] > 1 for identity in ids):
        issues.append(
            {
                "code": "duplicate_record_id",
                "message": "Coding households have duplicate identities; correct their identity fields.",
            }
        )
    municipalities = [
        identity_municipality(dwelling, household, index)
        for index, household in enumerate(dwelling["households"])
    ]
    values = [
        str(value).lstrip("0")
        for value in [dwelling["municipality"].get("value"), *municipalities]
        if value is not None
    ]
    if len(set(values)) > 1:
        issues.append(
            {
                "code": "municipality_mismatch",
                "message": "Coding cards disagree on municipality; check each card's municipality.",
            }
        )
    flags = set(dwelling.get("flags", []))
    structural = {
        "persons_unassigned": (
            len(dwelling["households"]) > 1,
            "Person rows have not been assigned to households; identity edits do not assign them.",
        ),
        "unplaced": (
            not any(
                card["role"] == "survey-front" for card in dwelling.get("cards", [])
            ),
            "This coding card has no associated survey front.",
        ),
        "fronts_disagree": (
            sum(card["role"] == "survey-front" for card in dwelling.get("cards", []))
            > 1,
            "Associated survey fronts disagree; editing the stored reading does not resolve their association.",
        ),
        "no_coding_card": (
            not any(
                card["role"] == "coding-front"
                for household in dwelling["households"]
                for card in household.get("cards", [])
            ),
            "This dwelling has no coding card.",
        ),
        "unread_coding_card": (
            True,
            "A coding card was not read; identity edits do not recover its fields.",
        ),
        "missing_dwelling_no": (
            True,
            "The survey front's dwelling number was missing; check its grouping separately from coding identity.",
        ),
        "duplicate_dwelling_no": (
            True,
            "Survey fronts share a dwelling number; coding edits do not resolve their grouping.",
        ),
        "unread_front": (
            True,
            "A survey front was not read; its grouping still needs checking.",
        ),
    }
    for code, (unresolved, message) in structural.items():
        if code in flags and unresolved:
            issues.append({"code": code, "message": message})
    return issues


def identity_alias(record, pointer):
    """The first card's municipality is also stored on its dwelling."""
    if pointer == "/dwelling/municipality":
        alias = "/dwelling/households/0/municipality"
    elif pointer == "/dwelling/households/0/municipality":
        alias = "/dwelling/municipality"
    else:
        return None, None
    node = record
    try:
        for part in alias.split("/")[1:]:
            node = node[int(part)] if isinstance(node, list) else node[part]
    except KeyError:
        return None, None
    return alias, node


class ReviewService:
    def __init__(
        self,
        store: RecordStore,
        references: list[Reference],
        diagnostics: list[dict],
        scans: ScanSource,
    ):
        self.store, self.scans = store, scans
        self.identity_counts = {}
        # Filled by build_card_registry at the end of replace_queue.
        self.voluntary_references, self.voluntary_by_card = {}, {}
        self.region_titles = self.load_region_titles()
        self.replace_queue(references, diagnostics)
        self.requests, self.decisions = self.store.requests, self.store.decisions

    def replace_queue(
        self, references: list[Reference], diagnostics: list[dict]
    ) -> None:
        """Merge a fresh flagged scope without rewriting any review data.

        Invalid/stale references remain diagnostics, even when their logical ID
        collides with a valid reference. Existing editors retain region versions.
        """
        with self.store.lock:
            self.assignment_references = list(references)
            self.assignment_diagnostics = deepcopy(diagnostics)
            valid = {}
            errors = deepcopy(diagnostics)
            for assignment_index, ref in enumerate(references):
                try:
                    from survey.review.prepared_service import rebind_reference

                    ref = rebind_reference(self, ref)
                    if ref is None:
                        continue  # retained supplementary evidence is outside the queue
                    resolved, _ = self.store.current(ref)
                    if resolved.front_page is not None:
                        ref = replace(ref, front_page=resolved.front_page)
                        self.assignment_references[assignment_index] = ref
                except ReviewError as error:
                    errors.append(
                        {
                            "item_id": ref.item_id,
                            "region": ref.region,
                            "batch": ref.pdf,
                            "page": ref.page,
                            "field_path": ref.field_path,
                            "code": error.code,
                            "message": str(error),
                        }
                    )
                else:
                    valid[ref.item_id] = ref
            self.references, self.diagnostics = valid, errors
            self.region_references = {}
            for ref in valid.values():
                self.region_references.setdefault(ref.region, []).append(ref)
            self.diagnostic_counts = {}
            for diagnostic in errors:
                key = diagnostic.get("region"), diagnostic.get("batch")
                self.diagnostic_counts[key] = self.diagnostic_counts.get(key, 0) + 1
            self.rebuild_progress()
            from survey.review.prepared_service import build_card_registry

            build_card_registry(self)

    def reindex_history(self, regions=None):
        self.requests, self.decisions = self.store.requests, self.store.decisions
        if any(
            r["schema_version"] == SCHEMA_VERSION
            for records, _ in self.store.regions.values()
            for r in records
        ):
            if regions is None:
                self.replace_queue(
                    self.assignment_references, self.assignment_diagnostics
                )
            else:
                from survey.review.prepared_service import refresh_regions

                refresh_regions(self, regions)
            return
        if regions is None:
            self.rebuild_progress()
        else:
            self.rebuild_progress(regions)

    def rebuild_progress(self, regions=None):
        if regions is None:
            self.progress = {}
            self.item_resolved = {}
            self.batch_revisions = {}
            self.progress_diagnostics = {}
            selected = self.references.values()
        else:
            selected = (
                ref
                for region in regions
                for ref in self.region_references.get(region, [])
            )
            for item_id, diagnostic in list(self.progress_diagnostics.items()):
                if diagnostic["region"] in regions:
                    del self.progress_diagnostics[item_id]
            for key in list(self.progress):
                if key[0] in regions:
                    del self.progress[key]
        for ref in selected:
            key = ref.region, ref.pdf
            counts = self.progress.setdefault(key, [0, 0])
            counts[0] += 1
            try:
                resolved, _ = self.store.current(ref)
                # Probe only decided fields: pending entries cannot complete a batch.
                done = state(resolved.field) != "pending" and not any(
                    "notes" in household
                    for household in resolved.record["dwelling"]["households"]
                )
                if done:
                    self.scans.probe(ref)
                    if resolved.front_page is not None:
                        self.scans.probe(
                            Reference(ref.region, ref.pdf, resolved.front_page, "/")
                        )
            except ReviewError as error:
                done = False
                self.progress_diagnostics[ref.item_id] = {
                    "item_id": ref.item_id,
                    "region": ref.region,
                    "batch": ref.pdf,
                    "page": ref.page,
                    "field_path": ref.field_path,
                    "code": error.code,
                    "message": str(error),
                }
            self.item_resolved[ref.item_id] = done
            counts[1] += int(done)
        if regions is None:
            self.dwelling_references = {}
        else:
            self.dwelling_references = {
                key: refs
                for key, refs in self.dwelling_references.items()
                if refs[0].region not in regions
            }
        for ref in (
            self.references.values()
            if regions is None
            else (r for rg in regions for r in self.region_references.get(rg, []))
        ):
            try:
                record = self.store.current(ref)[0].record
            except ReviewError:
                continue
            identity = self.dwelling_id(ref.region, record)
            self.dwelling_references.setdefault(identity, []).append(ref)
        revision = getattr(self.scans, "revision", None)
        if revision:
            for region, batch in self.progress:
                if regions is None or region in regions:
                    self.batch_revisions[(region, batch)] = revision(region, batch)

    def update_progress(self, item):
        previous = self.item_resolved.get(item["id"], False)
        self.item_resolved[item["id"]] = item["resolved"]
        key = item["region"], item["batch"]
        self.progress[key][1] += int(item["resolved"]) - int(previous)

    def batch_complete(self, region, batch):
        """Constant-time completion check; diagnostics always block completion."""
        with self.store.lock:
            revision = getattr(self.scans, "revision", None)
            if revision and revision(region, batch) != self.batch_revisions.get(
                (region, batch)
            ):
                self.rebuild_progress({region})
            total, resolved = self.progress.get((region, batch), (0, 0))
            errors = sum(
                self.diagnostic_counts.get(key, 0)
                for key in (
                    (None, None),
                    (region, None),
                    (None, batch),
                    (region, batch),
                )
            )
            return total > 0 and total == resolved and not errors

    def reference(self, item_id: str) -> Reference:
        try:
            return (
                self.references[item_id]
                if item_id in self.references
                else self.voluntary_references[item_id]
            )
        except KeyError as error:
            raise ReviewError(
                "missing_item", "Item is not in the supplied flagged set", 404
            ) from error

    def item(self, item_id: str, *, context: bool = True) -> dict:
        with self.store.lock:
            ref = self.reference(item_id)
            resolved, version = self.store.current(ref)
            warnings, errors = [], []
            try:
                self.scans.probe(ref)
                if resolved.front_page is not None:
                    self.scans.probe(
                        Reference(ref.region, ref.pdf, resolved.front_page, "/")
                    )
            except ReviewError as error:
                errors.append({"code": error.code, "message": str(error)})
            if any(
                "notes" in household
                for household in resolved.record["dwelling"]["households"]
            ):
                errors.append(
                    {
                        "code": "legacy_notes",
                        "message": "Migrate legacy household notes to dwelling.notes with verified front/back provenance before review. No notes were discarded.",
                    }
                )
            spec = resolved.descriptor.spec
            field = resolved.field
            if (
                spec.code_book_category in CLOSED_CATEGORIES
                and field.get("value") is not None
                and decode(spec.code_book_category, field["value"]) is None
            ):
                warnings.append("Unknown numeric code retained exactly")
            if spec.kind == "unknown":
                warnings.append("Codebook coverage for this field is unresolved")
            restricted = resolved.descriptor.accept_only or field.get("negated") is True
            if restricted:
                warnings.append(
                    "Accept-only field: if wrong, leave unresolved; editing is deferred"
                )
            if "negated" not in field:
                warnings.append(
                    "Crossed-out detection is unknown; this does not mean unstruck"
                )
            history = field.get("review", {}).get("history", [])
            active = active_decisions(history)
            item = {
                "id": item_id,
                "region": ref.region,
                "batch": ref.pdf,
                "record_id": resolved.household["record_id"]
                if resolved.descriptor.role == "coding-front"
                or len(resolved.record["dwelling"]["households"]) == 1
                else None,
                "field_path": ref.field_path,
                "label": resolved.label,
                "identity_kind": resolved.descriptor.identity_kind,
                # Prepared records take theirs from item_details below.
                "review_issues": []
                if resolved.record["schema_version"] == SCHEMA_VERSION
                else identity_issues(
                    resolved.record, self.region_identity_counts(ref.region, version)
                ),
                "field": deepcopy(field),
                "review_state": state(field),
                "version": version,
                "source": {
                    "pdf": ref.pdf,
                    "page": ref.page,
                    "card_id": ref.card_id,
                    "role": resolved.descriptor.role,
                    "front_page": resolved.front_page,
                },
                "scan_url": f"/api/scans/{ref.card_id}",
                "reason": ref.reason,
                "allowed_actions": []
                if errors
                else ["accept"]
                if restricted
                else ["accept", "correct"]
                if resolved.descriptor.identity_kind
                else ["accept", "correct", "no_data", "illegible"],
                "warnings": warnings,
                "diagnostics": errors,
                "resolved": state(field) != "pending" and not errors,
                "undo_decision_id": active[-1]["id"] if active else None,
            }

            item.update(self.item_context(ref, resolved, context))
            if resolved.record["schema_version"] == SCHEMA_VERSION:
                from survey.review.prepared_service import item_details

                item.update(item_details(self, ref, resolved))
            return item

    def region_identity_counts(self, region, version):
        cached = self.identity_counts.get(region)
        if cached is None or cached[0] != version:
            counts = Counter(
                identity
                for record in self.store.regions[region][0]
                for identity in identity_ids(record)
            )
            self.identity_counts[region] = (version, counts)
        return self.identity_counts[region][1]

    def load_region_titles(self):
        root = getattr(self.scans, "root", None)
        if root is None:
            return {}
        try:
            with (root / "metadata.csv").open(
                encoding="utf-8-sig", newline=""
            ) as stream:
                return {
                    row["Node ID"].strip(): (
                        row.get("Node Title") or row.get("Title") or ""
                    ).strip()
                    for row in csv.DictReader(stream)
                    if row.get("Node ID")
                }
        except (OSError, UnicodeError, csv.Error):
            return {}

    @staticmethod
    def coding_cards(record):
        return [
            card
            for household in record["dwelling"]["households"]
            for card in household.get("cards", [])
            if card["role"] == "coding-front"
        ]

    @classmethod
    def physical_cards(cls, record):
        return cls.coding_cards(record) + record["dwelling"].get("cards", [])

    @classmethod
    def dwelling_id(cls, region, record):
        locations = sorted(
            ((card["image"], card.get("page")) for card in cls.coding_cards(record)),
            key=lambda location: (location[0], location[1] or 0),
        )
        return digest(json.dumps([region, locations]).encode())

    def item_context(self, ref, resolved, context):
        spec = resolved.descriptor.spec
        codes = CLOSED_CATEGORIES.get(spec.code_book_category, {}) | SENTINEL_CODES.get(
            spec.code_book_category, {}
        )
        card = next(
            card
            for card in (
                resolved.household["cards"]
                if resolved.descriptor.role == "coding-front"
                else resolved.record["dwelling"].get("cards", [])
            )
            if card["role"] == resolved.descriptor.role
            and card["image"] == ref.pdf
            and card.get("page") == ref.page
        )
        details = {
            "column": printed_column(resolved.label)
            if resolved.descriptor.role == "coding-front"
            else "Interview notes"
            if resolved.group == "notes"
            else "Survey front",
            "household_count": len(resolved.record["dwelling"]["households"]),
            "dwelling_flags": resolved.record["dwelling"].get("flags", []),
            "dwelling_id": self.dwelling_id(ref.region, resolved.record),
            "address": resolved.record["dwelling"].get("address", {}).get("value"),
            "region_title": self.region_titles.get(ref.region) or None,
            "card_score": card.get("confidence"),
            "field_kind": spec.kind,
            "code_list": [
                {"value": value, "label": label} for value, label in codes.items()
            ],
        }
        if not context:
            return details
        fields = []
        index = resolved.record["dwelling"]["households"].index(resolved.household)
        shared = Reference(ref.region, ref.pdf, ref.page, "/dwelling/municipality")
        household_ref = Reference(
            ref.region,
            ref.pdf,
            ref.page,
            f"/dwelling/households/{index}/municipality",
        )
        # Generated assignments flag the shared alias on the first coding card.
        # Prefer it when the household copy is not independently queued.
        prefer_shared = (
            index == 0
            and shared.item_id in self.references
            and household_ref.item_id not in self.references
        )
        pointers = [
            (label, path)
            for label, path, _ in field_pointers(
                index,
                review=resolved.record["schema_version"] == SCHEMA_VERSION,
                household_municipality=(
                    "municipality" in resolved.household and not prefer_shared
                ),
                include_shared=index == 0,
            )
        ]
        if (
            index == 0
            and shared.item_id in self.references
            and not any(pointer == shared.field_path for _, pointer in pointers)
        ):
            # Explicit assignments can include both independently stored copies.
            pointers.insert(0, ("Municipality", shared.field_path))
        pointers.extend(
            ("Interview Notes", f"/dwelling/notes/{n}/text")
            for n in range(len(resolved.record["dwelling"].get("notes", [])))
        )
        for label, pointer in pointers:
            field_ref = Reference(ref.region, ref.pdf, ref.page, pointer)
            try:
                candidate = self.store.current(field_ref)[0]
                field = candidate.field
                if candidate.front_page is not None:
                    field_ref = replace(field_ref, front_page=candidate.front_page)
            except ReviewError:
                continue
            fields.append(
                {
                    "id": field_ref.item_id
                    if field_ref.item_id in self.references
                    or field_ref.item_id in self.voluntary_references
                    else None,
                    "label": label,
                    "column": printed_column(label)
                    if candidate.descriptor.role == "coding-front"
                    else "Interview notes"
                    if candidate.group == "notes"
                    else "Survey front",
                    "field_path": pointer,
                    "field": snapshot(field),
                    "review_state": state(field),
                }
            )
        details["card_fields"] = fields
        cards = []
        dwelling_refs = self.dwelling_references.get(details["dwelling_id"], [])
        owners = list(enumerate(resolved.record["dwelling"]["households"]))
        owners.append((None, {"cards": resolved.record["dwelling"].get("cards", [])}))
        for index, household in owners:
            for card in household.get("cards", []):
                if card["role"] not in {"coding-front", "survey-front", "survey-back"}:
                    continue
                refs = [
                    candidate
                    for candidate in dwelling_refs
                    if candidate.pdf == card["image"]
                    and candidate.page == card.get("page")
                ]
                if card["role"] != "coding-front" and not refs:
                    continue
                count = sum(
                    self.item_resolved.get(candidate.item_id, False)
                    for candidate in refs
                )
                errors = any(
                    diagnostic.get("region") in {None, ref.region}
                    and diagnostic.get("batch") in {None, card["image"]}
                    and diagnostic.get("page") in {None, card.get("page")}
                    for diagnostic in [
                        *self.diagnostics,
                        *self.progress_diagnostics.values(),
                    ]
                )
                cards.append(
                    {
                        "card_id": physical_card_id(
                            ref.region, card["image"], card.get("page")
                        ),
                        "score": card.get("confidence"),
                        # Review confidence is separate from machine confidence.
                        # Only supplied fields count; absent flags are not decisions.
                        "reviewed": bool(refs) and count == len(refs) and not errors,
                        "total": len(refs),
                        "resolved": count,
                        "unresolved": len(refs) - count,
                        "household_index": index,
                        "role": card["role"],
                        "household_no": household.get("household_no", {}).get("value"),
                        "record_id": household.get("record_id"),
                        "page": card.get("page"),
                        "first_item_id": refs[0].item_id
                        if refs
                        else next(
                            (
                                r.item_id
                                for r in self.voluntary_by_card.get(
                                    physical_card_id(
                                        ref.region, card["image"], card.get("page")
                                    ),
                                    [],
                                )
                            ),
                            None,
                        ),
                        "next_item_id": next(
                            (
                                candidate.item_id
                                for candidate in refs
                                if not self.item_resolved.get(candidate.item_id, False)
                            ),
                            None,
                        ),
                    }
                )
        # Stable sorting preserves printed order within each progress group.
        details["cards"] = sorted(cards, key=lambda card: card["reviewed"])
        return details

    def dwelling_groups(self, region=None):
        # Keep first occurrence in the supplied flags; no frontend reranking.
        groups = {}
        for identity, refs in self.dwelling_references.items():
            if region and refs[0].region != region:
                continue
            try:
                record = self.store.current(refs[0])[0].record
            except ReviewError:
                continue
            groups[identity] = (record, refs)
        return groups

    def region_summary(self, region=None):
        records = [
            record
            for key, (entries, _) in self.store.regions.items()
            if not region or key == region
            for record in entries
        ]
        cards = [card for record in records for card in self.coding_cards(record)]
        scores = [
            card["confidence"] for card in cards if card.get("confidence") is not None
        ]
        return {
            "dwellings": len(records),
            "average_card_score": sum(scores) / len(scores) if scores else None,
            "scored_cards": len(scores),
            "unscored_cards": len(cards) - len(scores),
        }

    def dwellings(self, region=None):
        with self.store.lock:
            for key in list(self.progress):
                self.batch_complete(*key)
            all_diagnostics = [*self.diagnostics, *self.progress_diagnostics.values()]
            diagnostic_index = {}
            for position, diagnostic in enumerate(all_diagnostics):
                key = (
                    diagnostic.get("region") or None,
                    diagnostic.get("batch") or None,
                    diagnostic.get("page") or None,
                )
                diagnostic_index.setdefault(key, []).append((position, diagnostic))

            def errors_for(
                region: str, locations: set[tuple[str, int | None]]
            ) -> list[dict]:
                # Match broad region/batch errors as well as exact physical cards.
                keys = {(None, None, None), (region, None, None)}
                for image, page in locations:
                    for scope in (None, region):
                        keys.add((scope, image, None))
                        keys.add((scope, image, page))
                matches = {
                    position: diagnostic
                    for key in keys
                    for position, diagnostic in diagnostic_index.get(key, [])
                }
                return [deepcopy(matches[position]) for position in sorted(matches)]

            diagnostics = [
                deepcopy(d)
                for d in all_diagnostics
                if not region or not d.get("region") or d["region"] == region
            ]
            groups = self.dwelling_groups()
            rows = []
            for identity, (record, refs) in groups.items():
                if region and refs[0].region != region:
                    continue
                cards = self.coding_cards(record)
                scores = [card.get("confidence") for card in cards]
                count = sum(self.item_resolved.get(ref.item_id, False) for ref in refs)
                errors = errors_for(
                    refs[0].region,
                    {
                        (card["image"], card.get("page"))
                        for card in self.physical_cards(record)
                    },
                )
                histories = [
                    event
                    for _, field in current_fields(record)
                    for event in field.get("review", {}).get("history", [])
                ]
                if any(
                    "notes" in household
                    for household in record["dwelling"]["households"]
                ):
                    legacy = {
                        "region": refs[0].region,
                        "batch": refs[0].pdf,
                        "page": refs[0].page,
                        "code": "legacy_notes",
                        "message": "Migrate legacy household notes before review. No notes were discarded.",
                    }
                    errors.append(legacy)
                    diagnostics.append(legacy)
                latest = max(
                    histories, key=lambda event: event["timestamp"], default=None
                )
                rows.append(
                    {
                        "id": identity,
                        "region": refs[0].region,
                        "record_id": record["dwelling"]["households"][0].get(
                            "record_id"
                        ),
                        "address": record["dwelling"].get("address", {}).get("value"),
                        "score": min(scores) if scores and None not in scores else None,
                        "card_count": len(cards),
                        "total": len(refs),
                        "resolved": count,
                        "unresolved": len(refs) - count,
                        "status": "blocked"
                        if errors
                        else "complete"
                        if count == len(refs)
                        else "in_progress"
                        if count
                        else "pending",
                        "next_item_id": next(
                            (
                                ref.item_id
                                for ref in refs
                                if not self.item_resolved.get(ref.item_id, False)
                            ),
                            None,
                        ),
                        "first_item_id": refs[0].item_id,
                        "last_reviewer": latest["reviewer"] if latest else None,
                        "last_reviewed_at": latest["timestamp"] if latest else None,
                        "diagnostics": errors,
                    }
                )
            # Completed dwellings remain available for inspection and undo.
            # Unfinished work retains the supplied queue's priority order.
            rows.sort(key=lambda row: row["status"] == "complete")
            resolved = sum(row["resolved"] for row in rows)
            # Dynamic diagnostics describe an existing supplied reference, never an
            # extra flag. Even references that no longer resolve remain in scope.
            total = sum(
                not region or ref.region == region for ref in self.references.values()
            ) + sum(
                not region or not d.get("region") or d["region"] == region
                for d in self.diagnostics
            )
            summary = self.region_summary(region)
            summary["queued_dwellings"] = len(rows)
            summary["completed_dwellings"] = sum(
                row["status"] == "complete" for row in rows
            )
            all_regions = self.region_summary()
            all_regions["queued_dwellings"] = len(groups)
            all_regions["completed_dwellings"] = sum(
                all(self.item_resolved.get(ref.item_id, False) for ref in refs)
                and not errors_for(
                    refs[0].region,
                    {
                        (card["image"], card.get("page"))
                        for card in self.physical_cards(record)
                    },
                )
                for record, refs in groups.values()
            )
            links = Counter()
            for rg, (records, _) in self.store.regions.items():
                if region is not None and rg != region:
                    continue
                for r in records:
                    for h in r["dwelling"]["households"]:
                        links["duplicate_cards"] += "duplicate_record_id" in h.get(
                            "flags", []
                        )
                        links["pending_links"] += h.get("relink", {}).get("state") in {
                            "pending",
                            "provisional",
                        }
                        links["retained_bundles"] += len(
                            h.get("retained_supplements", [])
                        )
            return {
                "dwellings": rows,
                "association_summary": {
                    key: links[key]
                    for key in ("duplicate_cards", "pending_links", "retained_bundles")
                },
                "diagnostics": diagnostics,
                "total": total,
                "resolved": resolved,
                "unresolved": total - resolved,
                "complete": total > 0 and total == resolved,
                "summary": summary,
                "all_regions": all_regions,
                "region_title": self.region_titles.get(region) or None,
                "scope": {"region": region, "basis": "supplied flagged fields only"},
            }

    def dwelling_items(self, dwelling_id, region=None):
        with self.store.lock:
            group = self.dwelling_groups(region).get(dwelling_id)
            if group is None:
                if any(
                    r["schema_version"] == SCHEMA_VERSION
                    and self.dwelling_id(rg, r) == dwelling_id
                    for rg, (records, _) in self.store.regions.items()
                    if region is None or rg == region
                    for r in records
                ):
                    return {
                        "items": [],
                        "diagnostics": [],
                        "total": 0,
                        "resolved": 0,
                        "unresolved": 0,
                        "complete": False,
                        "scope": {
                            "region": region,
                            "basis": "supplied flagged fields only",
                        },
                    }
                raise ReviewError(
                    "missing_dwelling",
                    "Dwelling is not in the supplied flagged set for this region",
                    404,
                )
            order = {
                label: index
                for index, label in enumerate(spec.name for spec in FIELD_SCHEMA)
            }
            front_order = {
                label: i for i, label in enumerate(SURVEY_FRONT_DWELLING_FIELDS)
            }

            def field_order(ref):
                resolved = self.store.current(ref)[0]
                return (
                    order if resolved.descriptor.role == "coding-front" else front_order
                ).get(resolved.label, len(front_order))

            physical = self.physical_cards(group[0])
            refs = sorted(
                group[1],
                key=lambda ref: (
                    next(
                        i
                        for i, card in enumerate(physical)
                        if card["image"] == ref.pdf and card.get("page") == ref.page
                    ),
                    field_order(ref),
                ),
            )
            items = [self.item(ref.item_id, context=False) for ref in refs]
            for item in items:
                self.update_progress(item)
            resolved = sum(item["resolved"] for item in items)
            cards = self.physical_cards(group[0])
            diagnostics = [
                deepcopy(d)
                for d in [*self.diagnostics, *self.progress_diagnostics.values()]
                if (not d.get("region") or d["region"] == refs[0].region)
                and (
                    not d.get("batch")
                    or d["batch"] in {card["image"] for card in cards}
                )
                and (
                    not d.get("page")
                    or any(
                        card["image"] == d.get("batch")
                        and card.get("page") == d["page"]
                        for card in cards
                    )
                )
            ]
            item_ids = {item["id"] for item in items}
            total = len(items) + sum(
                d.get("item_id") not in item_ids for d in diagnostics
            )
            return {
                "items": items,
                "diagnostics": diagnostics,
                "total": total,
                "resolved": resolved,
                "unresolved": total - resolved,
                "complete": bool(items) and resolved == total,
                "scope": {"region": region, "basis": "supplied flagged fields only"},
            }

    def queue(self, region: str | None = None, batch: str | None = None) -> dict:
        with self.store.lock:
            items = []
            diagnostics = [
                d
                for d in self.diagnostics
                if (not region or not d.get("region") or d["region"] == region)
                and (not batch or not d.get("batch") or d["batch"] == batch)
            ]
            for item_id, ref in self.references.items():
                if (region and region != ref.region) or (batch and batch != ref.pdf):
                    continue
                try:
                    item = self.item(item_id, context=False)
                    self.update_progress(item)
                    items.append(item)
                except ReviewError as error:
                    diagnostics.append(
                        {
                            "item_id": item_id,
                            "region": ref.region,
                            "batch": ref.pdf,
                            "code": error.code,
                            "message": str(error),
                        }
                    )
            resolved = sum(i["resolved"] for i in items)
            total = len(items) + len(diagnostics)
            return {
                "items": items,
                "diagnostics": diagnostics,
                "total": total,
                "resolved": resolved,
                "unresolved": total - resolved,
                "complete": total > 0 and total == resolved,
                "scope": {
                    "region": region,
                    "batch": batch,
                    "basis": "supplied flagged fields only",
                },
            }

    def apply_decision(
        self,
        item_id: str,
        action: str,
        reviewer: str,
        expected_version: str,
        request_id: str,
        value: str | None = None,
        undo_target: str | None = None,
        duplicate_confirmation: str | None = None,
    ) -> dict:
        prior = self.requests.get(request_id)
        target = self.decisions.get(undo_target) if undo_target else None
        ref = (
            self.reference(item_id)
            if prior is None and not (target and "card_id" in target)
            else None
        )
        if (
            (prior and "card_id" in prior)
            or (target and "card_id" in target)
            or (
                ref
                and self.store.current(ref)[0].record["schema_version"]
                == SCHEMA_VERSION
            )
        ):
            from survey.review.prepared_service import apply_decision

            return apply_decision(
                self,
                item_id,
                action,
                reviewer,
                expected_version,
                request_id,
                value,
                undo_target,
                duplicate_confirmation,
            )
        reviewer = credentials(reviewer, request_id)
        request = {
            "action": action,
            "value": value,
            "expected_version": expected_version,
            "undo_target": undo_target,
        }
        with self.store.lock:
            if prior := self.requests.get(request_id):
                if (
                    prior["item_id"] != item_id
                    or prior["reviewer"] != reviewer
                    or prior["request"] != request
                ):
                    raise ReviewError(
                        "request_conflict",
                        "Request ID was already used for different input",
                        409,
                    )
                return {
                    "item": self.item(item_id),
                    "decision": deepcopy(prior),
                    "replayed": True,
                    "saved_locally": True,
                }
            ref = self.reference(item_id)
            self.store.current(ref)
            self.store.check_version(ref.region, expected_version)
            item = self.item(item_id)
            if item["diagnostics"]:
                migration = next(
                    (
                        error
                        for error in item["diagnostics"]
                        if error["code"] == "legacy_notes"
                    ),
                    None,
                )
                if migration:
                    raise ReviewError(migration["code"], migration["message"])
                raise ReviewError(
                    "missing_scan", "Review requires the original readable scan", 404
                )
            # A metadata probe cannot prove that compressed image pixels decode.
            # Recheck/render the selected original before committing a decision.
            self.scans.get_scan(ref)
            if ref.front_page is not None:
                self.scans.get_scan(Reference(ref.region, ref.pdf, ref.front_page, "/"))
            current, _ = self.store.current(ref)
            record = deepcopy(current.record)
            resolved = resolve_field([record], ref)
            field = resolved.field
            before, before_state = snapshot(field), state(field)
            history = deepcopy(field.get("review", {}).get("history", []))
            if action == "undo":
                if value is not None:
                    raise ReviewError("invalid_action", "Undo does not accept a value")
                active = active_decisions(history)
                if not active or active[-1]["id"] != undo_target:
                    raise ReviewError(
                        "undo_conflict",
                        "Only the latest applicable decision for this item can be undone",
                        409,
                    )
                target = active[-1]
                after, after_state = deepcopy(target["before"]), target["before_state"]
            else:
                if undo_target is not None or action not in item["allowed_actions"]:
                    raise ReviewError(
                        "unsupported_action", "Action is unsupported for this field"
                    )
                if action != "correct" and value is not None:
                    raise ReviewError(
                        "invalid_value", "Only correction accepts a value"
                    )
                after = field_after(field, resolved.descriptor, action, value)
                after_state = "accepted" if action == "accept" else "corrected"
                if after == before and after_state == before_state:
                    raise ReviewError(
                        "no_op",
                        "This decision is already recorded; no new history was added",
                    )
            event = {
                "id": str(uuid4()),
                "request_id": request_id,
                "item_id": item_id,
                "reviewer": reviewer,
                "timestamp": datetime.now(UTC).isoformat(),
                "action": action,
                "before": before,
                "after": deepcopy(after),
                "before_state": before_state,
                "after_state": after_state,
                "request": request,
            }
            if undo_target:
                event["undo_target"] = undo_target
            if resolved.descriptor.identity_kind:
                alias_path, alias = identity_alias(record, ref.field_path)
                if action == "undo":
                    for change in target.get("identity_changes", []):
                        if alias_path != change["path"] or (
                            snapshot(alias) != change["after"]
                            or active_decisions(
                                alias.get("review", {}).get("history", [])
                            )
                        ):
                            raise ReviewError(
                                "undo_conflict",
                                "The municipality copy was reviewed or changed later; undo that change first",
                                409,
                            )
                        alias_review = deepcopy(alias.get("review"))
                        alias.clear()
                        alias.update(deepcopy(change["before"]))
                        if alias_review is not None:
                            alias["review"] = alias_review
                elif (
                    action == "correct"
                    and alias is not None
                    and alias.get("value") != after.get("value")
                ):
                    if alias.get("negated") is True:
                        raise ReviewError(
                            "identity_conflict",
                            "The other municipality copy is crossed out; editing it is deferred",
                            409,
                        )
                    if active_decisions(alias.get("review", {}).get("history", [])):
                        raise ReviewError(
                            "identity_conflict",
                            "The other municipality copy has review history; undo its decisions before changing this value",
                            409,
                        )
                    alias_before = snapshot(alias)
                    alias_review = deepcopy(alias.get("review"))
                    alias_after = deepcopy(alias_before)
                    alias_after.update(
                        value=after["value"],
                        status="ok",
                        code=after.get("code"),
                        label=after.get("label"),
                        origin="corrected",
                    )
                    alias_after.setdefault("original_value", alias_before.get("value"))
                    event["identity_changes"] = [
                        {
                            "path": alias_path,
                            "before": alias_before,
                            "after": alias_after,
                        }
                    ]
                    alias.clear()
                    alias.update(alias_after)
                    if alias_review is not None:
                        alias["review"] = alias_review
            history.append(event)
            field.clear()
            field.update(after, review={"state": after_state, "history": history})
            if resolved.descriptor.identity_kind and action != "accept":
                if action == "undo":
                    if (
                        target.get("identity_links")
                        and "identity_note_topology" not in target
                    ) or (
                        "identity_note_topology" in target
                        and identity_note_topology(record)
                        != target["identity_note_topology"]
                    ):
                        raise ReviewError(
                            "undo_conflict",
                            "Associated notes changed since this identity correction; check their ownership before undoing",
                            409,
                        )
                    for change in target.get("identity_ids", []):
                        household = record["dwelling"]["households"][change["index"]]
                        if household.get("record_id") != change["after"]:
                            raise ReviewError(
                                "undo_conflict",
                                "Another identity field changed later; undo that change first",
                                409,
                            )
                        household["record_id"] = change["before"]
                    for change in target.get("identity_links", []):
                        note = record["dwelling"]["notes"][change["index"]]
                        if note.get("household_id") != change["after"]:
                            raise ReviewError(
                                "undo_conflict",
                                "A linked note changed later; undo that change first",
                                409,
                            )
                        note["household_id"] = change["before"]
                    self.check_identity_collisions(
                        [h.get("record_id") for h in record["dwelling"]["households"]],
                        [
                            h.get("record_id")
                            for h in current.record["dwelling"]["households"]
                        ],
                        ref.region,
                        current.record_index,
                        identity_ids(record),
                        target.get("identity_conflicts"),
                    )
                else:
                    event["identity_note_topology"] = identity_note_topology(record)
                    conflicts = self.identity_collision_owners(
                        ref.region,
                        {
                            household.get("record_id")
                            for household in current.record["dwelling"]["households"]
                        },
                    )
                    if conflicts:
                        event["identity_conflicts"] = conflicts
                    link_changes, id_changes = self.rebuild_identity_ids(
                        record,
                        current.record,
                        ref.region,
                        current.record_index,
                        ref.field_path,
                    )
                    if link_changes:
                        event["identity_links"] = link_changes
                    if id_changes:
                        event["identity_ids"] = id_changes
            resolved.record["schema_version"] = review_schema_version(
                record["schema_version"]
            )
            self.store.save_record(
                ref.region, expected_version, current.record_index, record
            )
            self.requests[request_id] = event
            self.decisions[event["id"]] = event
            saved_item = self.item(item_id, context=False)
            self.update_progress(saved_item)
            # Navigation metadata must reflect the decision just recorded.
            saved_item = self.item(item_id)
            return {
                "item": saved_item,
                "decision": deepcopy(event),
                "replayed": False,
                "saved_locally": True,
            }

    def rebuild_identity_ids(self, record, original, region, record_index, pointer):
        old_ids = [
            household.get("record_id")
            for household in original["dwelling"]["households"]
        ]
        affected = (
            range(len(old_ids))
            if pointer == "/dwelling/dwelling_no"
            else [0]
            if pointer == "/dwelling/municipality"
            else [int(pointer.split("/")[3])]
        )
        affected = set(affected)
        overrides = {}
        if pointer == "/dwelling/municipality" or (
            record["dwelling"]["municipality"].get("value")
            != original["dwelling"]["municipality"].get("value")
        ):
            for index, household in enumerate(record["dwelling"]["households"]):
                if "municipality" not in household and (
                    index == 0 or not household.get("record_id")
                ):
                    overrides[index] = record["dwelling"]["municipality"].get("value")
                    affected.add(index)
        for index in affected:
            household = record["dwelling"]["households"][index]
            if (
                index
                and "municipality" not in household
                and not household.get("record_id")
                and "municipality_mismatch" in record["dwelling"].get("flags", [])
            ):
                raise ReviewError(
                    "identity_conflict",
                    "Legacy household lost its municipality; rebuild from cache before editing identity",
                    409,
                )
        derived = identity_ids(record, overrides)
        ids = [
            derived[index] if index in affected else old_id
            for index, old_id in enumerate(old_ids)
        ]
        self.check_identity_collisions(ids, old_ids, region, record_index, derived)
        for household, identity in zip(record["dwelling"]["households"], ids):
            household["record_id"] = identity
        changes = []
        for index, note in enumerate(record["dwelling"].get("notes", [])):
            linked = note.get("household_id")
            if (linked is not None and old_ids.count(linked) == 1) or (
                linked is None and len(ids) == 1
            ):
                new_link = ids[0] if linked is None else ids[old_ids.index(linked)]
                if new_link != linked:
                    changes.append(
                        {"index": index, "before": linked, "after": new_link}
                    )
                    note["household_id"] = new_link
        return changes, [
            {"index": index, "before": old, "after": new}
            for index, (old, new) in enumerate(zip(old_ids, ids))
            if index in affected
        ]

    @staticmethod
    def identity_owner(region, household):
        cards = sorted(
            physical_card_id(region, card["image"], card.get("page"))
            for card in household.get("cards", [])
            if card["role"] == "coding-front"
        )
        return digest(json.dumps(cards).encode()) if cards else None

    def identity_collision_owners(self, region, identities):
        """Remember original conflict owners so Undo can restore known defects."""
        owners = {identity: set() for identity in identities if identity is not None}
        unknown = set()
        for record in self.store.regions[region][0]:
            for household, derived in zip(
                record["dwelling"]["households"], identity_ids(record)
            ):
                owner = self.identity_owner(region, household)
                for identity in {household.get("record_id"), derived} & owners.keys():
                    if owner is None:
                        unknown.add(identity)
                    else:
                        owners[identity].add(owner)
        return [
            {"identity": identity, "owners": sorted(values)}
            for identity, values in sorted(owners.items())
            if len(values) > 1 and identity not in unknown
        ]

    def check_identity_collisions(
        self, ids, old_ids, region, record_index, derived, allowed_conflicts=None
    ):
        permitted = {
            entry["identity"]: set(entry["owners"]) for entry in allowed_conflicts or []
        }
        for index, identity in enumerate(ids):
            if identity is None or identity == old_ids[index]:
                continue
            conflicts = set()
            for other_index, other_record in enumerate(self.store.regions[region][0]):
                stored = (
                    ids
                    if other_index == record_index
                    else [
                        h.get("record_id")
                        for h in other_record["dwelling"]["households"]
                    ]
                )
                candidate_ids = (
                    derived
                    if other_index == record_index
                    else identity_ids(other_record)
                )
                for household_index, household in enumerate(
                    other_record["dwelling"]["households"]
                ):
                    if other_index == record_index and household_index == index:
                        continue
                    if identity in {
                        stored[household_index],
                        candidate_ids[household_index],
                    }:
                        conflicts.add(self.identity_owner(region, household))
            if conflicts and (
                None in conflicts or not conflicts <= permitted.get(identity, set())
            ):
                raise ReviewError(
                    "identity_conflict",
                    "That coding identity already belongs to another household; records cannot be merged in review",
                    409,
                )

    def undo_latest(
        self, decision_id: str, reviewer: str, expected_version: str, request_id: str
    ) -> dict:
        with self.store.lock:
            event = self.decisions.get(decision_id)
            if not event:
                raise ReviewError("missing_decision", "Unknown decision", 404)
            if event.get("card_id") and self.card_registry.get(
                event["card_id"], {}
            ).get("retained"):
                raise ReviewError(
                    "retained_evidence",
                    "Restore the retained evidence before undoing a supplementary field decision",
                    409,
                )
            if event.get("request", {}).get("action") == "link":
                from survey.review.prepared_service import undo_link

                return undo_link(self, event, reviewer, expected_version, request_id)
            return self.apply_decision(
                event["item_id"],
                "undo",
                reviewer,
                expected_version,
                request_id,
                undo_target=decision_id,
            )

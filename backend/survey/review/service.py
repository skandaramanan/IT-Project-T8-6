"""Review policy independent of HTTP. Every decision is embedded in JSONL."""

import csv
import json
from copy import deepcopy
from dataclasses import replace
from datetime import UTC, datetime
from uuid import uuid4

from survey.extraction.card_fields import (
    FIELD_SCHEMA,
    SURVEY_FRONT_DWELLING_FIELDS,
)
from survey.extraction.code_book import CLOSED_CATEGORIES, SENTINEL_CODES, decode
from survey.extraction.record import FIELD_MAP, SCHEMA_VERSION
from survey.extraction.survey_front import record_key
from survey.records import (
    RecordStore,
    Reference,
    ReviewError,
    current_fields,
    digest,
    physical_card_id,
    resolve_field,
)
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


class ReviewService:
    def __init__(
        self,
        store: RecordStore,
        references: list[Reference],
        diagnostics: list[dict],
        scans: ScanSource,
    ):
        self.store, self.scans = store, scans
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
            valid = {}
            errors = deepcopy(diagnostics)
            for ref in references:
                try:
                    resolved, _ = self.store.current(ref)
                    if resolved.front_page is not None:
                        ref = replace(ref, front_page=resolved.front_page)
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

    def reindex_history(self, regions=None):
        self.requests, self.decisions = self.store.requests, self.store.decisions
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
        self.dwelling_references = {}
        for ref in self.references.values():
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
            return self.references[item_id]
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
                else ["accept", "correct", "no_data", "illegible"],
                "warnings": warnings,
                "diagnostics": errors,
                "resolved": state(field) != "pending" and not errors,
                "undo_decision_id": active[-1]["id"] if active else None,
            }

            item.update(self.item_context(ref, resolved, context))
            return item

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
        pointers = []
        for field_spec in FIELD_SCHEMA:
            label = field_spec.name
            key, group = FIELD_MAP[label]
            if label == "Municipality" and "municipality" in resolved.household:
                group = "household"
            if group in {"dwelling", "house"} and index != 0:
                continue
            pointers.append(
                (
                    label,
                    (
                        f"/dwelling/{key}"
                        if group == "dwelling"
                        else f"/dwelling/house/{key}"
                        if group == "house"
                        else f"/dwelling/households/{index}/{key}"
                        if group == "household"
                        else f"/dwelling/households/{index}/{group}/{key}"
                    ),
                )
            )
        for label in SURVEY_FRONT_DWELLING_FIELDS:
            key = record_key(label)
            pointers.append(
                (
                    label,
                    f"/dwelling/{key}"
                    if key in {"address", "families_in_dwelling"}
                    else f"/dwelling/handwritten/{key}",
                )
            )
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
        # Keep supplied flags for the legacy shared alias actionable as well.
        shared = Reference(ref.region, ref.pdf, ref.page, "/dwelling/municipality")
        if (
            index == 0
            and shared.item_id in self.references
            and not any(field["field_path"] == shared.field_path for field in fields)
        ):
            field = self.store.current(shared)[0].field
            fields.insert(
                0,
                {
                    "id": shared.item_id,
                    "label": "Municipality",
                    "field_path": shared.field_path,
                    "field": snapshot(field),
                    "review_state": state(field),
                },
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
                cards.append(
                    {
                        "card_id": physical_card_id(
                            ref.region, card["image"], card.get("page")
                        ),
                        "score": card.get("confidence"),
                        "household_index": index,
                        "role": card["role"],
                        "household_no": household.get("household_no", {}).get("value"),
                        "record_id": household.get("record_id"),
                        "page": card.get("page"),
                        "first_item_id": refs[0].item_id if refs else None,
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
        details["cards"] = cards
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
            return {
                "dwellings": rows,
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
    ) -> dict:
        reviewer = reviewer.strip()
        if not reviewer or len(reviewer) > 100:
            raise ReviewError(
                "invalid_reviewer", "Enter a reviewer name (1–100 characters)"
            )
        if not request_id or len(request_id) > 128:
            raise ReviewError(
                "invalid_request_id", "Supply a request ID (1–128 characters)"
            )
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
                after = deepcopy(before)
                after_state = "accepted" if action == "accept" else "corrected"
                if action == "correct":
                    if not resolved.descriptor.valid_correction(value):
                        raise ReviewError(
                            "invalid_value",
                            "Enter nonblank text exactly as written"
                            if resolved.descriptor.spec.kind == "text"
                            else "Enter 1–64 ASCII digits; zeros are preserved",
                        )
                    category = resolved.descriptor.spec.code_book_category
                    coded = category in CLOSED_CATEGORIES or category in SENTINEL_CODES
                    after.update(
                        value=value,
                        status="ok",
                        code=value if coded else None,
                        label=decode(category, value) if coded else None,
                    )
                elif action in {"no_data", "illegible"}:
                    after.update(value=None, status=action, code=None, label=None)
                if action != "accept":
                    after.setdefault(
                        "original_value", before.get("original_value", before["value"])
                    )
                    after["origin"] = "corrected"
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
            history.append(event)
            field.clear()
            field.update(after, review={"state": after_state, "history": history})
            resolved.record["schema_version"] = (
                "0.5.0" if record["schema_version"] == "0.5.0" else SCHEMA_VERSION
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

    def undo_latest(
        self, decision_id: str, reviewer: str, expected_version: str, request_id: str
    ) -> dict:
        with self.store.lock:
            event = self.decisions.get(decision_id)
            if not event:
                raise ReviewError("missing_decision", "Unknown decision", 404)
            return self.apply_decision(
                event["item_id"],
                "undo",
                reviewer,
                expected_version,
                request_id,
                undo_target=decision_id,
            )

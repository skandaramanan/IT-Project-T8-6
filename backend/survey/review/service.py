"""Review policy independent of HTTP. Every decision is embedded in JSONL."""

import re
from copy import deepcopy
from datetime import UTC, datetime
from uuid import uuid4

from survey.extraction.card_fields import FIELD_SCHEMA_BY_NAME
from survey.extraction.code_book import CLOSED_CATEGORIES, SENTINEL_CODES, decode
from survey.extraction.record import SCHEMA_VERSION
from survey.records import (
    RecordStore,
    Reference,
    ReviewError,
    resolve_field,
)
from survey.review.scans import ScanSource


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
                    self.store.current(ref)
                except ReviewError as error:
                    errors.append(
                        {
                            "item_id": ref.item_id,
                            "region": ref.region,
                            "batch": ref.pdf,
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
            selected = self.references.values()
        else:
            selected = (
                ref
                for region in regions
                for ref in self.region_references.get(region, [])
            )
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
                done = state(resolved.field) != "pending"
                if done:
                    self.scans.probe(ref)
            except ReviewError:
                done = False
            self.item_resolved[ref.item_id] = done
            counts[1] += int(done)
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

    def item(self, item_id: str) -> dict:
        with self.store.lock:
            ref = self.reference(item_id)
            resolved, version = self.store.current(ref)
            warnings, errors = [], []
            try:
                self.scans.probe(ref)
            except ReviewError as error:
                errors.append({"code": error.code, "message": str(error)})
            spec = FIELD_SCHEMA_BY_NAME[resolved.label]
            field = resolved.field
            if (
                spec.code_book_category in CLOSED_CATEGORIES
                and field.get("value") is not None
                and decode(spec.code_book_category, field["value"]) is None
            ):
                warnings.append("Unknown numeric code retained exactly")
            if spec.kind == "unknown":
                warnings.append("Codebook coverage for this field is unresolved")
            restricted = (
                resolved.group in {"dwelling", "household"}
                or field.get("negated") is True
            )
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
            return {
                "id": item_id,
                "region": ref.region,
                "batch": ref.pdf,
                "record_id": resolved.household["record_id"],
                "field_path": ref.field_path,
                "label": resolved.label,
                "field": deepcopy(field),
                "review_state": state(field),
                "version": version,
                "source": {"pdf": ref.pdf, "page": ref.page, "card_id": ref.card_id},
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
                    item = self.item(item_id)
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
                raise ReviewError(
                    "missing_scan", "Review requires the original readable scan", 404
                )
            # A metadata probe cannot prove that compressed image pixels decode.
            # Recheck/render the selected original before committing a decision.
            self.scans.get_scan(ref)
            current, _ = self.store.current(ref)
            record = deepcopy(current.record)
            locations = self.store.cards[ref.region][(ref.pdf, ref.page)]
            local_locations = {
                (ref.pdf, ref.page): [(0, h, primary) for _, h, primary in locations]
            }
            resolved = resolve_field([record], ref, local_locations)
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
                    if not isinstance(value, str) or not re.fullmatch(
                        r"[0-9]{1,64}", value
                    ):
                        raise ReviewError(
                            "invalid_value",
                            "Enter 1–64 ASCII digits; zeros are preserved",
                        )
                    category = FIELD_SCHEMA_BY_NAME[resolved.label].code_book_category
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
            resolved.record["schema_version"] = SCHEMA_VERSION
            self.store.save_record(
                ref.region, expected_version, current.record_index, record
            )
            self.requests[request_id] = event
            self.decisions[event["id"]] = event
            saved_item = self.item(item_id)
            self.update_progress(saved_item)
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

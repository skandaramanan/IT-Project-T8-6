"""The review queue (FR-11, D022): every coding-card field a batch sends to a
person, as the flags ``survey review --flags`` reads. Least sure card first,
each card's fields in form order."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from typing import Any

from survey.extraction.card_fields import FIELD_SCHEMA
from survey.extraction.record import FIELD_MAP, IDENTITY_LABELS
from survey.records import card_index, field_pointer
from survey.review.routing import needs_review
from survey.review.service import state


def _reason(field: Mapping[str, Any]) -> str:
    if field["status"] != "ok":
        return field["status"]
    if field.get("confidence") is None:
        return "no score"
    return f"score {field['confidence']}"


def _pointers(index: int) -> Iterator[tuple[int, str, str]]:
    """Household ``index``'s coding-card fields in printed order (FIELD_SCHEMA),
    as (order, label, pointer)."""
    for order, spec in enumerate(FIELD_SCHEMA):
        key, group = FIELD_MAP[spec.name]
        # Every household keeps its own municipality; the first's is the
        # dwelling's.
        if spec.name == "Municipality" and index:
            group = "household"
        # Other dwelling-level fields belong to the first household.
        elif group in {"dwelling", "house"} and index:
            continue
        yield order, spec.name, field_pointer(key, group, index)


def build_flags(
    regions: Mapping[str, list[dict]],
) -> tuple[list[dict], list[str]]:
    """``regions`` maps region to records. Returns the flags, and a message for
    each card or household that can't be flagged, which is skipped.

    A flagged dwelling's identity fields are queued whatever they score
    (D022), as its record_id can't be trusted."""
    keyed, skipped = [], []
    for region, records in regions.items():
        for record in records:
            for household in record["dwelling"]["households"]:
                if not any(
                    c["role"] == "coding-front" for c in household.get("cards", [])
                ):
                    skipped.append(
                        f"{region}: household {household['record_id']} has no "
                        "coding card"
                    )
        for (pdf, page), owners in card_index(records).items():
            if len(owners) > 1:
                skipped.append(f"{region}: {pdf} p{page} is on two households")
                continue
            if page is None:  # the review tool finds a card by its page
                skipped.append(f"{region}: a card in {pdf} has no page")
                continue
            record_index, index, primary = owners[0]
            if not primary:  # its fields are stored under the household's first card
                continue
            record = records[record_index]
            card = next(
                c
                for c in record["dwelling"]["households"][index].get("cards", [])
                if c["role"] == "coding-front"
            )
            score = card.get("confidence")
            dwelling_flags = record["dwelling"].get("flags", [])
            for order, label, pointer in _pointers(index):
                field = record
                try:
                    for part in pointer.split("/")[1:]:
                        field = (
                            field[int(part)] if isinstance(field, list) else field[part]
                        )
                except (KeyError, IndexError, TypeError):
                    continue  # not on this record, so nothing to review
                # Accepted or corrected is done; undo makes it pending again.
                # Older corrections carry only `origin`.
                if state(field) != "pending" or field.get("origin") == "corrected":
                    continue
                if needs_review(field):
                    reason = _reason(field)
                elif dwelling_flags and label in IDENTITY_LABELS:
                    reason = "dwelling flagged " + ", ".join(dwelling_flags)
                else:
                    continue
                flag = {
                    "region": region,
                    "pdf": pdf,
                    "page": page,
                    "field_path": pointer,
                    "reason": reason,
                }
                # A missing card score is the worst case (D022), so it sorts first.
                key = (score is not None, score or 0.0, region, pdf, page, order)
                keyed.append((key, flag))
    return [flag for _, flag in sorted(keyed, key=lambda k: k[0])], skipped

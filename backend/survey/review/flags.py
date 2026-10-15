"""The review queue (FR-11, D022): every coding-card field a batch sends to a
person, as the flags ``survey review --flags`` reads. Least sure card first,
each card's fields in form order."""

from survey.extraction.record import FIELD_MAP
from survey.records import card_index, field_pointer
from survey.review.routing import needs_review
from survey.review.service import state


def _reason(field):
    if field["status"] != "ok":
        return field["status"]
    if field.get("confidence") is None:
        return "no score"
    return f"score {field['confidence']}"


def build_flags(regions):
    """``regions`` maps region to records. Returns the flags, and a message for
    each card or household that can't be flagged, which is skipped."""
    keyed, skipped = [], []
    for region, records in regions.items():
        for record in records:
            for household in record["dwelling"]["households"]:
                if not any(c["role"] == "coding-front" for c in household["cards"]):
                    skipped.append(
                        f"{region}: household {household['record_id']} has no "
                        "coding card"
                    )
        for (pdf, page), owners in card_index(records).items():
            if len(owners) > 1:
                skipped.append(f"{region}: {pdf} p{page} is on two households")
                continue
            record_index, index, primary = owners[0]
            if not primary:  # its fields are stored under the household's first card
                continue
            record = records[record_index]
            card = next(
                c
                for c in record["dwelling"]["households"][index]["cards"]
                if c["role"] == "coding-front"
            )
            score = card["confidence"]
            for order, (key, group) in enumerate(FIELD_MAP.values()):
                # Dwelling-level fields belong to the first household.
                if group in {"dwelling", "house"} and index:
                    continue
                pointer = field_pointer(key, group, index)
                field = record
                try:
                    for part in pointer.split("/")[1:]:
                        field = (
                            field[int(part)] if isinstance(field, list) else field[part]
                        )
                except (KeyError, IndexError):
                    continue  # not on this record, so nothing to review
                # Accepted or corrected is done; undo makes it pending again.
                # Older corrections carry only `origin`.
                if (
                    state(field) != "pending"
                    or field.get("origin") == "corrected"
                    or not needs_review(field)
                ):
                    continue
                flag = {
                    "region": region,
                    "pdf": pdf,
                    "page": page,
                    "field_path": pointer,
                    "reason": _reason(field),
                }
                # A missing card score is the worst case (D022), so it sorts first.
                key = (score is not None, score or 0.0, region, pdf, page, order)
                keyed.append((key, flag))
    return [flag for _, flag in sorted(keyed, key=lambda k: k[0])], skipped

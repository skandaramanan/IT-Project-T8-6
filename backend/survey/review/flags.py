"""The review queue (FR-11, D022): every field a batch sends to a person, least
sure card first, as the flags ``survey review --flags`` reads."""

from typing import Any

from survey.review.routing import needs_review
from survey.review.service import state


def walk_fields(node: Any, path: tuple = ()):
    # D007 gives a `status` to every field and to nothing else.
    if isinstance(node, dict) and "status" in node:
        yield path, node
    elif isinstance(node, (dict, list)):
        for key, child in node.items() if isinstance(node, dict) else enumerate(node):
            yield from walk_fields(child, (*path, key))


def build_flags(records):
    keyed = []
    for record in records:
        for path, field in walk_fields(record):
            # Accepted or corrected is done; undo makes it pending again. Older
            # corrections carry only `origin`.
            if (
                state(field) != "pending"
                or field.get("origin") == "corrected"
                or not needs_review(field)
            ):
                continue
            # Dwelling-level fields belong to the first household's first card.
            household = record["dwelling"]["households"][
                path[2] if path[1] == "households" else 0
            ]
            cards = [c for c in household["cards"] if c["role"] == "coding-front"]
            if not cards:
                raise ValueError(f"{household['record_id']}: no coding card to flag")
            card = cards[0]
            score = card["confidence"]
            if field["status"] != "ok":
                reason = field["status"]
            elif field.get("confidence") is None:
                reason = "no score"
            else:
                reason = f"score {field['confidence']}"
            flag = {
                "region": record["region"],
                "pdf": card["image"],
                "page": card["page"],
                "field_path": "".join(f"/{part}" for part in path),
                "reason": reason,
            }
            # A missing card score is the worst case (D022), so it sorts first.
            key = (score is not None, score or 0.0, household["record_id"], path)
            keyed.append((key, record["region"], flag))
    return [flag for *_, flag in sorted(keyed, key=lambda k: k[:2])]

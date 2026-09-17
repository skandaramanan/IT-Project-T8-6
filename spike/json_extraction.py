"""Shared by every chat-prompted VLM adapter: the extraction prompt text and
best-effort JSON parsing of whatever the model actually said.
"""

from __future__ import annotations

import json
import re
from collections.abc import Collection

from extraction.field_schema import (
    FIELD_SCHEMA_BY_NAME,
    FIELD_STATUS_DEFINITIONS,
    FieldStatus,
    build_extraction_prompt_schema,
)

# Derived, not written down: the schema is now 62 fields for C1/C2 and 60 for
# C3, and a prompt that names the wrong count while listing the right keys is
# the kind of drift nothing fails on.
_SCHEMA_BLOCK = build_extraction_prompt_schema()

EXTRACTION_PROMPT = (
    "This is a numeric C1/C2 coding card from a 1941-43 social survey. Extract the "
    f"following {len(_SCHEMA_BLOCK.splitlines())} fields and return ONLY a JSON "
    "object with exactly these keys (no markdown fences, no commentary).\n\n"
    'For every key return an object: {"value": <string or null>, "status": '
    '"ok" | "no_data" | "illegible" | "damaged"}.\n\n'
    "Use ok only for a readable value. Use no_data for a visible blank cell; "
    "illegible where markings exist but cannot be read reliably; damaged where "
    "the source area is physically damaged or obscured. For every non-ok "
    "status, use null as the value and never guess. Attempt every field; the "
    "system records any absent expected key as omitted. Preserve leading zeros "
    "in readable codes.\n\n"
    + _SCHEMA_BLOCK
)

# The bands a model may self-report against a value. Categorical rather than a
# percentage, per Standup #7: raw LLM confidence numbers were judged too
# unreliable to drive an automated accept/reject, while a three-way banding is
# coarse enough to be meaningful and is what the review queue routes on.
CONFIDENCE_BANDS = ("low", "medium", "high")

# An opt-in variant of the prompt above, asking the model to say how sure it is
# of each value. Deliberately a second prompt rather than an edit to the first:
# changing EXTRACTION_PROMPT in place would make every previously saved raw
# response incomparable with new ones, and put D012's ~95% figure in doubt with
# no way to check it short of re-running everything. Keeping both means IT-100
# can measure whether asking for a band *costs* accuracy, which is a finding in
# its own right rather than an assumption.
BANDED_EXTRACTION_PROMPT = (
    "This is a numeric C1/C2 coding card from a 1941-43 social survey. Extract the "
    f"following {len(_SCHEMA_BLOCK.splitlines())} fields and return ONLY a JSON "
    "object with exactly these keys (no markdown fences, no commentary).\n\n"
    'The value for each key is an object: {"value": <the code>, "confidence": '
    '<"low"|"medium"|"high">, "status": "ok" | "no_data" | '
    '"illegible" | "damaged"}.\n\n'
    "Give every code as a JSON string, copied exactly as written, keeping any "
    'leading zeros ("04", not 4). Use null as the value where no code is '
    "written.\n\n"
    'Judge confidence on how clearly you can read that cell: "high" if the '
    'digits are unambiguous, "medium" if you had to choose between plausible '
    'readings, "low" if the cell is faint, damaged, overwritten or a guess. '
    "Say low when it is low -- a wrong value marked high is worse than an "
    "honest one marked low, because a reviewer will never look at it. "
    "Use ok only for a readable value; use no_data for a visible blank; "
    "illegible for unreadable markings; damaged for an obscured or damaged "
    "source area. For every non-ok status use null and never guess. Attempt "
    "every field; the system records any absent expected key as omitted.\n\n"
    + _SCHEMA_BLOCK
)

FIELD_STATUSES = frozenset(FIELD_STATUS_DEFINITIONS)
MODEL_FIELD_STATUSES = FIELD_STATUSES - {"omitted"}


def _unwrap(value) -> tuple[object, str | None]:
    """Split a banded ``{"value": ..., "confidence": ...}`` into its two halves.

    Tolerates the flat shape too, so one parser reads both prompts' output and
    nothing downstream has to know which prompt produced a given raw file --
    including a raw/ directory copied in from another machine.
    """
    if isinstance(value, dict) and "value" in value:
        band = value.get("confidence")
        band = band.lower() if isinstance(band, str) else None
        return value["value"], band if band in CONFIDENCE_BANDS else None
    return value, None


def _coerce_field(value) -> str:
    """Ground truth is stringly-typed; models emit JSON natives. null means the
    cell is blank on the card -> "" (matches the empty side of exact-match
    scoring), integral floats like 4.0 collapse to "4"."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def _open_braces(snippet: str) -> int:
    depth, in_string, escaped = 0, False, False
    for char in snippet:
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
        elif char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
    return max(depth, 0)


def _pair_boundaries(candidate: str) -> list[int]:
    """Offsets just after each complete top-level pair in a (possibly truncated)
    JSON object -- i.e. after each ',' or '}' that sits at depth 1 outside a
    string literal."""
    boundaries: list[int] = []
    depth, in_string, escaped = 0, False, False
    for index, char in enumerate(candidate):
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
        elif char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            boundaries.append(index + 1)
        elif char == "," and depth == 1:
            boundaries.append(index)
    return boundaries


def _repair_truncated_object(candidate: str) -> dict | None:
    """A response cut off mid-JSON (finish_reason=length) has all its complete
    key-value pairs intact up to the cut -- trim back to the last pair boundary,
    close the open braces, and salvage those pairs instead of scoring a zero."""
    for position in reversed(_pair_boundaries(candidate)):
        prefix = candidate[:position].rstrip()
        if prefix.endswith(","):
            prefix = prefix[:-1].rstrip()
        attempt = prefix + "}" * max(_open_braces(prefix), 0)
        try:
            parsed = json.loads(attempt)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed
    return None


def _parse_object(text: str | None) -> dict | None:
    """The response's JSON object, however the model wrapped it.

    Models routinely wrap JSON in ```json fences or add a sentence before/after
    despite being told not to -- pull out the first {...} block rather than
    requiring the whole response to be clean JSON.
    """
    if not text:
        return None
    match = re.search(r"\{.*\}", text, re.DOTALL) or re.search(r"\{.*", text, re.DOTALL)
    if not match:
        return None
    try:
        parsed = json.loads(match.group(0))
    except json.JSONDecodeError:
        parsed = _repair_truncated_object(match.group(0))
    return parsed if isinstance(parsed, dict) else None


def parse_json_fields(text: str | None) -> dict[str, str] | None:
    """The card's values, from either prompt's output."""
    parsed = _parse_object(text)
    if parsed is None:
        return None
    fields = {str(k): _coerce_field(_unwrap(v)[0]) for k, v in parsed.items()}
    # A response sharing no key with the schema is not a partial answer, it is a
    # different answer -- models sometimes emit a placeholder like
    # {"A": null, ..., "E": null}. That parses cleanly and every schema field
    # then reads as empty, which scores ~70% on a card that is mostly empty
    # cells. Reject it so the caller retries instead of banking a fake pass.
    if not any(name in FIELD_SCHEMA_BY_NAME for name in fields):
        return None
    return fields


def parse_confidence_bands(text: str | None) -> dict[str, str]:
    """The model's self-reported confidence per field, where it gave one.

    Empty for output of the unbanded prompt, and empty for any field the model
    answered flatly or banded with something outside CONFIDENCE_BANDS -- a
    made-up band is not a band. Absence has to stay distinguishable from "low",
    since one means the model was not asked and the other means it was and said
    it could not read the cell.
    """
    parsed = _parse_object(text) or {}
    bands = {}
    for name, value in parsed.items():
        band = _unwrap(value)[1]
        if band is not None:
            bands[str(name)] = band
    return bands


def parse_field_statuses(
    text: str | None, field_names: Collection[str] | None = None
) -> dict[str, FieldStatus] | None:
    """Read status-aware output without conflating omitted and blank fields.

    ``None`` means the response is not the status-aware shape.  A malformed
    status-aware response raises instead of silently falling back to legacy
    rules, because that would turn a broken classification into plausible data.
    """
    parsed = _parse_object(text)
    if parsed is None:
        return None
    expected = frozenset(FIELD_SCHEMA_BY_NAME if field_names is None else field_names)
    known = [(str(name), value) for name, value in parsed.items() if str(name) in expected]
    structured = [(name, value) for name, value in known if isinstance(value, dict)]
    if not any("status" in value for _, value in structured):
        # Historical banded output has value + confidence but no status. A
        # value object without either status or confidence is malformed rather
        # than a legacy response and must not silently bypass validation.
        if any("value" in value and "confidence" not in value for _, value in structured):
            raise ValueError("status-aware response lacks status")
        return None

    statuses: dict[str, FieldStatus] = {}
    reported = set()
    for name, value in known:
        if not isinstance(value, dict) or "value" not in value or "status" not in value:
            raise ValueError(f"status-aware response lacks value or status for {name}")
        status = value["status"]
        raw_value = value["value"]
        if not isinstance(status, str) or status not in MODEL_FIELD_STATUSES:
            raise ValueError(f"{name}: invalid FieldStatus {status!r}")
        if status == "ok" and (raw_value is None or not _coerce_field(raw_value).strip()):
            raise ValueError(f"{name}: ok status requires a readable value")
        if status != "ok" and raw_value is not None:
            raise ValueError(f"{name}: {status} status requires a null value")
        statuses[name] = status  # type: ignore[assignment]
        reported.add(name)
    statuses.update({name: "omitted" for name in expected - reported})
    return statuses

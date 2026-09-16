"""Shared by every chat-prompted VLM adapter: the extraction prompt text and
best-effort JSON parsing of whatever the model actually said.
"""

from __future__ import annotations

import json
import re

from extraction.field_schema import FIELD_SCHEMA_BY_NAME, build_extraction_prompt_schema

# Derived, not written down: the schema is now 62 fields for C1/C2 and 60 for
# C3, and a prompt that names the wrong count while listing the right keys is
# the kind of drift nothing fails on.
_SCHEMA_BLOCK = build_extraction_prompt_schema()

# Opens every prompt variant. Shared so the field count is derived once -- four
# copies of the same f-string is four chances for the drift the note above warns
# about.
_PROMPT_HEADER = (
    "This is a numeric coding card from a 1941-43 social survey. Extract the "
    f"following {len(_SCHEMA_BLOCK.splitlines())} fields and return ONLY a JSON "
    "object with exactly these keys (no markdown fences, no commentary).\n\n"
)

EXTRACTION_PROMPT = (
    _PROMPT_HEADER
    # Codes are written in fixed-width columns, so "04" and "4" are different
    # values -- as a JSON number the leading zero is unrepresentable and gets
    # silently dropped, which scored as a miss on every zero-padded field.
    + "Give every value as a JSON string, copied exactly as written, keeping any "
    'leading zeros ("04", not 4). Use null where no code is written.\n\n'
    + _SCHEMA_BLOCK
)

# The bands a model may self-report against a value. Categorical rather than a
# percentage, per Standup #7: raw LLM confidence numbers were judged too
# unreliable to drive an automated accept/reject, while a three-way banding is
# coarse enough to be meaningful and is what the review queue routes on.
CONFIDENCE_BANDS = ("low", "medium", "high")

# Shared by the banded and banded-struck prompts. This is prose and will get
# reworded; two copies would let a reword desynchronise the two banded arms
# without anything failing.
_CONFIDENCE_INSTRUCTIONS = (
    'Judge confidence on how clearly you can read that cell: "high" if the '
    'digits are unambiguous, "medium" if you had to choose between plausible '
    'readings, "low" if the cell is faint, damaged, overwritten or a guess. '
    "Say low when it is low -- a wrong value marked high is worse than an "
    "honest one marked low, because a reviewer will never look at it.\n\n"
)

# An opt-in variant of the prompt above, asking the model to say how sure it is
# of each value. Deliberately a second prompt rather than an edit to the first:
# changing EXTRACTION_PROMPT in place would make every previously saved raw
# response incomparable with new ones, and put D012's ~95% figure in doubt with
# no way to check it short of re-running everything. Keeping both means IT-100
# can measure whether asking for a band *costs* accuracy, which is a finding in
# its own right rather than an assumption.
BANDED_EXTRACTION_PROMPT = (
    _PROMPT_HEADER
    + 'The value for each key is an object: {"value": <the code>, "confidence": '
    '<"low"|"medium"|"high">}.\n\n'
    "Give every code as a JSON string, copied exactly as written, keeping any "
    'leading zeros ("04", not 4). Use null as the value where no code is '
    "written.\n\n" + _CONFIDENCE_INSTRUCTIONS + _SCHEMA_BLOCK
)


# FR-06 struck-option detection: a dedicated prompt, separate from
# EXTRACTION_PROMPT/BANDED_EXTRACTION_PROMPT. A VLM judgement call, not pixel
# geometry -- column-slash/boundary-overlap handling is untested against a
# real example. Composable with the confidence band (below) since they are
# independent per-field signals -- one call gets both instead of two.
def _struck_extraction_prompt(*, banded: bool) -> str:
    shape = (
        '{"value": <the code>, "confidence": <"low"|"medium"|"high">, "struck": <true|false>}'
        if banded
        else '{"value": <the code>, "struck": <true|false>}'
    )
    return (
        _PROMPT_HEADER + f"The value for each key is an object: {shape}.\n\n"
        # Deliberately EXTRACTION_PROMPT's wording, not the banded one's ("every
        # code", "null as the value"). The two diverged before this prompt
        # existed; normalising them would change an emitted string.
        "Give every value as a JSON string, copied exactly as written, keeping any "
        'leading zeros ("04", not 4). Use null where no code is written.\n\n'
        + (_CONFIDENCE_INSTRUCTIONS if banded else "")
        + 'Set "struck" to true only when that field\'s own printed option has a pen '
        "line or X drawn through it. A diagonal line drawn across an entire column "
        "of many fields is not a strike-through of any one option -- report struck: "
        "false for every field that line merely crosses, even though it passes "
        "through them. If a strike-through mark extends slightly past the edge of "
        "one field's box, attribute it to the field it clearly marks, not to the "
        "neighbouring field it only grazes.\n\n" + _SCHEMA_BLOCK
    )


STRUCK_EXTRACTION_PROMPT = _struck_extraction_prompt(banded=False)
BANDED_STRUCK_EXTRACTION_PROMPT = _struck_extraction_prompt(banded=True)


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


def parse_struck_fields(text: str | None) -> dict[str, bool]:
    """Fields the model flagged struck-through. Only True entries are kept,
    same convention as parse_confidence_bands."""
    parsed = _parse_object(text) or {}
    struck = {}
    for name, value in parsed.items():
        if isinstance(value, dict) and value.get("struck") is True:
            struck[str(name)] = True
    return struck

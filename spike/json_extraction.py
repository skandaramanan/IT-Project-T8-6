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

EXTRACTION_PROMPT = (
    "This is a numeric coding card from a 1941-43 social survey. Extract the "
    f"following {len(_SCHEMA_BLOCK.splitlines())} fields and return ONLY a JSON "
    "object with exactly these keys (no markdown fences, no commentary).\n\n"
    # Codes are written in fixed-width columns, so "04" and "4" are different
    # values -- as a JSON number the leading zero is unrepresentable and gets
    # silently dropped, which scored as a miss on every zero-padded field.
    "Give every value as a JSON string, copied exactly as written, keeping any "
    'leading zeros ("04", not 4). Use null where no code is written.\n\n'
    + _SCHEMA_BLOCK
)


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


def parse_json_fields(text: str | None) -> dict[str, str] | None:
    """Models routinely wrap JSON in ```json fences or add a sentence before/after
    despite being told not to -- pull out the first {...} block rather than
    requiring the whole response to be clean JSON."""
    if not text:
        return None
    match = re.search(r"\{.*\}", text, re.DOTALL) or re.search(r"\{.*", text, re.DOTALL)
    if not match:
        return None
    try:
        parsed = json.loads(match.group(0))
    except json.JSONDecodeError:
        parsed = _repair_truncated_object(match.group(0))
        if parsed is None:
            return None
    if not isinstance(parsed, dict):
        return None
    fields = {str(k): _coerce_field(v) for k, v in parsed.items()}
    # A response sharing no key with the schema is not a partial answer, it is a
    # different answer -- models sometimes emit a placeholder like
    # {"A": null, ..., "E": null}. That parses cleanly and every schema field
    # then reads as empty, which scores ~70% on a card that is mostly empty
    # cells. Reject it so the caller retries instead of banking a fake pass.
    if not any(name in FIELD_SCHEMA_BY_NAME for name in fields):
        return None
    return fields

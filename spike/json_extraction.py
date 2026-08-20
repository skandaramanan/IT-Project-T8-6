"""Shared by every chat-prompted VLM adapter: the extraction prompt text and
best-effort JSON parsing of whatever the model actually said.
"""

from __future__ import annotations

import json
import re

from extraction.field_schema import build_extraction_prompt_schema

EXTRACTION_PROMPT = (
    "This is a numeric coding card from a 1941-43 social survey. Extract the "
    "following 60 fields and return ONLY a JSON object with exactly these keys "
    "(no markdown fences, no commentary):\n\n" + build_extraction_prompt_schema()
)


def parse_json_fields(text: str) -> dict[str, str] | None:
    """Models routinely wrap JSON in ```json fences or add a sentence before/after
    despite being told not to -- pull out the first {...} block rather than
    requiring the whole response to be clean JSON."""
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        return None
    try:
        parsed = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    if not isinstance(parsed, dict):
        return None
    return {str(k): str(v) for k, v in parsed.items()}

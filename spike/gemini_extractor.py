"""Gemini: hosted multimodal LLM, prompted directly against the field schema.

Env vars, because ``run_benchmark.py`` constructs extractors with no args:

    GEMINI_API_KEY              from https://aistudio.google.com/apikey
    GEMINI_MODEL                default gemini-3.6-flash
    GEMINI_MEDIA_RESOLUTION     low | medium | high; unset = the model's default
    GEMINI_CONFIDENCE_BAND      1 to have the model self-report low/medium/high
                                per field; off by default

Default model is flash-lite: its free-tier cap (500/day/key) is what lets a
~6,500-card corpus run at all, at a 2.4-point accuracy cost vs Flash (91.3%
vs 93.7% coded). Batched flash-lite is much worse (-23 points, stops reading
after ~3 cards) -- single-card only.

Media resolution is left unset by default; Gemini 3 downscales to a flat
1120 tokens then, which is a thumbnail for ~2660x1715 handwriting -- set
GEMINI_MEDIA_RESOLUTION when switching to a 3.x model.

Every current prompt returns a visual status beside each value. The parser
derives ``omitted`` for C1/C2 schema fields the model does not return; the
model itself may only report ``ok``, ``no_data``, ``illegible`` or ``damaged``.
New results use a ``-status`` suffix so they cannot overwrite older flat runs.

FR-10: this engine returns ``confidence=None``. Gemini's response_logprobs
isn't reliably available, so D012 built self-reported bands instead, behind
GEMINI_CONFIDENCE_BAND (off by default -- it's a different prompt, so a
different experiment; banded runs file under ``<model>-banded-status``). The
band stays a category, not a number -- turning "high" into 0.9 is IT-99's call
-- so it travels in ``raw_text`` for ``json_extraction.parse_confidence_bands``
to read back, and ``confidence`` stays None even when banded.

The batched path follows ``self.banded`` via ``banded_batch_prompt`` and uses
the same value/status or value/confidence/status shape as the single-card path.
Re-measure batched status runs before treating them as comparable to earlier
flat-output measurements.
"""

from __future__ import annotations

import json
import mimetypes
import os
import re
import time
from pathlib import Path

from json_extraction import (
    BANDED_EXTRACTION_PROMPT,
    EXTRACTION_PROMPT,
    parse_field_statuses,
    parse_json_fields,
)

from extraction.base import ExtractionResult
from extraction.field_schema import build_extraction_prompt_schema

DEFAULT_MODEL = "gemini-3.5-flash-lite"

# USD per million tokens (input, output). Unlisted model -> cost_usd=None.
PRICE_PER_MTOK = {
    # 3.6/3.7 Flash promo pricing through 2026-12-31, then $1.50/$7.50.
    "gemini-3.6-flash": (0.75, 3.75),
    "gemini-3.7-flash": (0.75, 3.75),
    "gemini-3.5-flash": (1.50, 9.00),
    "gemini-3.5-flash-lite": (0.30, 2.50),
    "gemini-3.1-flash-lite": (0.25, 1.50),
    "gemini-3.1-pro-preview": (2.00, 12.00),
}

# Free tier is ~10-15 RPM; --workers above 2 mostly spends time in backoff.
RATE_LIMIT_BACKOFF_SECONDS = 30

# 429/503/500 are worth retrying with different waits (quota clears on the
# minute, capacity clears in seconds); anything else is our problem, not transient.
RETRYABLE = {
    "429": RATE_LIMIT_BACKOFF_SECONDS,
    "RESOURCE_EXHAUSTED": RATE_LIMIT_BACKOFF_SECONDS,
    "503": 5,
    "UNAVAILABLE": 5,
    "500": 5,
    "INTERNAL": 5,
}


def _retry_wait(error: Exception, attempt: int) -> float | None:
    """Seconds to wait before retrying this error, or None if it is terminal.

    Markers match on word boundaries so a token-count number like 1500 doesn't
    false-positive as a 500.
    """
    text = str(error)
    waits = [
        base
        for marker, base in RETRYABLE.items()
        if re.search(rf"\b{re.escape(marker)}\b", text)
    ]
    return max(waits) * attempt if waits else None


def batch_prompt(count: int) -> str:
    """Ask for ``count`` cards in one request, keyed "1".."count".

    Uses the same schema builder as ``EXTRACTION_PROMPT`` so batched and
    single-card stay comparable.
    """
    schema = build_extraction_prompt_schema()
    return (
        f"You are given {count} numeric coding cards from a 1941-43 social "
        f"survey, labelled CARD 1 to CARD {count}, each immediately after its "
        "label.\n\n"
        "Return ONLY a JSON object (no markdown fences, no commentary) whose "
        f'keys are "1" to "{count}" and whose value for each key is that '
        f"card's field object, containing exactly these "
        f"{len(schema.splitlines())} keys.\n\n"
        'For each field return an object: {"value": <string or null>, "status": '
        '"ok" | "no_data" | "illegible" | "damaged"}. Read each '
        "card independently and completely. Use ok only for a readable value; "
        "use no_data for a visible blank, illegible for unreadable markings, "
        "damaged for an obscured or damaged source area. For every non-ok status "
        "use null and never guess. Attempt every field; the system records any "
        "absent expected key as omitted. Preserve leading zeros.\n\n" + schema
    )


def _parse_batch_object(raw: str) -> dict:
    """The ``{"1": {...}, "2": {...}}`` object out of a batched response.

    Anything else parses as an empty batch, not an exception.
    """
    try:
        parsed = json.loads(raw[raw.index("{") : raw.rindex("}") + 1])
    except (ValueError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def banded_batch_prompt(count: int) -> str:
    """``batch_prompt``, but each field includes value, confidence and status.

    This is the batched form of
    ``json_extraction.BANDED_EXTRACTION_PROMPT``.
    """
    schema = build_extraction_prompt_schema()
    return (
        f"You are given {count} numeric coding cards from a 1941-43 social "
        f"survey, labelled CARD 1 to CARD {count}, each immediately after its "
        "label.\n\n"
        "Return ONLY a JSON object (no markdown fences, no commentary) whose "
        f'keys are "1" to "{count}" and whose value for each key is that '
        f"card's field object, containing exactly these "
        f"{len(schema.splitlines())} keys.\n\n"
        'The value for each key is an object: {"value": <the code>, "confidence": '
        '<"low"|"medium"|"high">, "status": "ok" | "no_data" | '
        '"illegible" | "damaged"}.\n\n'
        "Read each card independently and completely. Give every code as a "
        'JSON string, copied exactly as written, keeping any leading zeros ("04", '
        "not 4). Use null as the value where no code is written.\n\n"
        'Judge confidence on how clearly you can read that cell: "high" if the '
        'digits are unambiguous, "medium" if you had to choose between plausible '
        'readings, "low" if the cell is faint, damaged, overwritten or a guess. '
        "Say low when it is low -- a wrong value marked high is worse than an "
        "honest one marked low, because a reviewer will never look at it. "
        "Use ok only for a readable value; use no_data for a visible blank; "
        "illegible for unreadable markings; damaged for an obscured or damaged "
        "source area. For every non-ok status use null and never guess. Attempt "
        "every field; the system records any absent expected key as omitted.\n\n"
        + schema
    )


def _call_with_retry(call, attempts: int = 3):
    """Retry transient API failures. Shared by the single and batched paths --
    a 503 on a batched request would otherwise throw away every card in it."""
    for attempt in range(1, attempts + 1):
        try:
            return call()
        except Exception as error:  # SDK error types vary by transport
            wait = _retry_wait(error, attempt)
            if wait is None or attempt == attempts:
                raise
            time.sleep(wait)


class GeminiExtractor:
    def __init__(self) -> None:
        # name is the results directory; must carry the model id since every
        # Gemini model shares one CLI key, or 3.5-flash overwrites 3.6-flash's output.
        self.model_id = os.environ.get("GEMINI_MODEL", DEFAULT_MODEL)
        self.name = self.model_id
        # Banded is a different prompt/run, so it gets a "-banded" suffix to
        # keep results side by side instead of overwriting.
        self.banded = os.environ.get("GEMINI_CONFIDENCE_BAND", "").strip().lower() in (
            "1",
            "true",
            "yes",
        )
        self.status_aware = True
        self.name += "-banded-status" if self.banded else "-status"

    def is_available(self) -> bool:
        try:
            import google.genai  # noqa: F401
        except ImportError:
            return False
        return bool(os.environ.get("GEMINI_API_KEY"))

    @staticmethod
    def _part(image_path: Path):
        from google.genai import types

        mime = mimetypes.types_map.get(image_path.suffix.lower(), "image/jpeg")
        return types.Part.from_bytes(data=image_path.read_bytes(), mime_type=mime)

    @staticmethod
    def _config():
        from google.genai import types

        resolution = os.environ.get("GEMINI_MEDIA_RESOLUTION")
        return types.GenerateContentConfig(
            media_resolution=(
                f"MEDIA_RESOLUTION_{resolution.upper()}" if resolution else None
            ),
        )

    def extract_batch(self, image_paths: list[Path]) -> list[ExtractionResult]:
        """Extract several cards in one request.

        Duck-typed rather than added to the Extractor protocol -- only hosted
        models have reason to batch, and run_benchmark looks for this method.

        flash-lite loses ~23 accuracy points batched (stops reading after ~3
        cards, fabricates the rest) -- ``cost_usd`` is the per-card share so
        that's visible; re-measure before trusting a new model or batch size.
        """
        from google import genai

        prompt = banded_batch_prompt if self.banded else batch_prompt
        contents: list = [prompt(len(image_paths))]
        for index, path in enumerate(image_paths, start=1):
            contents += [f"CARD {index}:", self._part(path)]

        client = genai.Client()
        # Retry an unusable answer (same as _generate) so a bad first response
        # doesn't cost the whole batch.
        outer: dict = {}
        for attempt in range(1, 4):
            response = _call_with_retry(
                lambda: client.models.generate_content(
                    model=self.model_id, contents=contents, config=self._config()
                )
            )
            outer = _parse_batch_object(response.text or "")
            if outer or attempt == 3:
                break
            time.sleep(2**attempt)

        share = _cost_usd(self.model_id, response.usage_metadata)
        results = []
        for index in range(1, len(image_paths) + 1):
            card = outer.get(str(index))
            # Round-trip through parse_json_fields for the same coercion a
            # single-card response gets; an omitted slot becomes {}.
            text = json.dumps(card) if card is not None else ""
            results.append(
                ExtractionResult(
                    fields=parse_json_fields(text) or {},
                    raw_text=text,
                    cost_usd=share / len(image_paths) if share is not None else None,
                    statuses=parse_field_statuses(text),
                )
            )
        return results

    def extract(self, image_path: Path) -> ExtractionResult:
        from google import genai

        model = self.model_id
        prompt = BANDED_EXTRACTION_PROMPT if self.banded else EXTRACTION_PROMPT
        contents = [self._part(image_path), prompt]
        config = self._config()

        client = genai.Client()  # reads GEMINI_API_KEY
        response = self._generate(client, model, contents, config)
        raw_output = response.text or ""
        return ExtractionResult(
            fields=parse_json_fields(raw_output) or {},
            raw_text=raw_output,
            cost_usd=_cost_usd(model, response.usage_metadata),
            statuses=parse_field_statuses(raw_output),
        )

    @staticmethod
    def _generate(client, model, contents, config, attempts: int = 3):
        """Retry on throttling and on a response with no usable JSON in it.

        A response that stays unparseable after retries is returned, not
        raised, so the raw file still gets written and scored as a miss --
        raising would leave it looking like a card never attempted, and every
        later run would re-buy it for the same result. Only a call that never
        comes back at all raises.
        """
        last_error: Exception | None = None
        last_response = None
        for attempt in range(1, attempts + 1):
            try:
                response = client.models.generate_content(
                    model=model, contents=contents, config=config
                )
            except Exception as error:  # SDK error types vary by transport
                wait = _retry_wait(error, attempt)
                if wait is None or attempt == attempts:
                    if last_response is not None:
                        return last_response
                    raise
                last_error = error
                time.sleep(wait)
                continue
            last_response = response
            if parse_json_fields(response.text) is not None:
                return response
            if attempt == attempts:
                return response
            last_error = RuntimeError(
                f"Gemini returned no usable JSON "
                f"(finish_reason={_finish_reason(response)!r}): "
                f"{(response.text or '')[:200]!r}"
            )
            time.sleep(2**attempt)
        assert last_error is not None
        raise last_error


def _finish_reason(response) -> str | None:
    candidates = getattr(response, "candidates", None) or []
    return str(getattr(candidates[0], "finish_reason", None)) if candidates else None


def _cost_usd(model: str, usage) -> float | None:
    """Estimate this card's cost. Split out so it is testable without an API key.

    Thinking tokens bill at the output rate and aren't included in
    candidates_token_count, so they're added in separately.
    """
    price = PRICE_PER_MTOK.get(model)
    if price is None or usage is None:
        return None
    input_rate, output_rate = price
    billed_output = (usage.candidates_token_count or 0) + (
        getattr(usage, "thoughts_token_count", None) or 0
    )
    return (
        (usage.prompt_token_count or 0) * input_rate + billed_output * output_rate
    ) / 1_000_000

"""Gemini: hosted multimodal LLM, prompted directly against the field schema.

Unlike Azure Document Intelligence this needs no training step -- it takes the
same ``EXTRACTION_PROMPT`` every VLM candidate gets, so its number is directly
comparable to ox-alpha's rather than to a model fitted on six labelled cards.

Three knobs, all env vars because ``run_benchmark.py`` constructs extractors
with no arguments:

    GEMINI_API_KEY              from https://aistudio.google.com/apikey
    GEMINI_MODEL                default gemini-3.6-flash
    GEMINI_MEDIA_RESOLUTION     low | medium | high; unset = the model's default

Default model is gemini-3.6-flash: it is Google's named replacement for
gemini-2.5-flash, which ``models.list`` still advertises but which 404s for
keys created after its retirement ("no longer available to new users"). Listing
a model is not the same as being able to call it -- check by calling. Flash,
not Pro, because Pro-class models left the free tier on 2026-04-01, and the
$300 Google Cloud trial credit has excluded Gemini API usage since March 2026.
gemini-3.7-flash is newer and same price but was returning 503 UNAVAILABLE
("high demand") on every attempt as of 2026-09-02; retry it later.

Free tier is ~10-15 RPM and prompts may be used to improve Google's products --
fine for 30 benchmark cards that are already in a shared Drive, not fine for
the archive. Check your live numbers at https://aistudio.google.com/rate-limit.

Media resolution caps the tokens Gemini spends looking at the image, so it is
the knob that decides whether the model sees these cards at all: ~2660x1715 of
handwritten digits in ruled columns is exactly the "fine text" case the docs
say to raise it for. Left unset by default, which on 2.5 means pan-and-scan
(~2k tokens) and on Gemini 3 means a flat 1120-token downscale -- so if you
switch GEMINI_MODEL to a 3.x model, set this too or you are benchmarking a
thumbnail. Sweep it before concluding anything about the model. Gemini 3's
``ultra_high`` (2240) is per-content-item and not in google-genai 2.21's
MediaResolution enum: passing it warns and falls through to the API.

FR-10: this engine returns ``confidence=None``. Gemini's ``response_logprobs``
is not reliably enabled past 2.0 -- Gemini 3 rejects it outright ("Logprobs is
not supported for this model") and 2.5 Flash has been observed returning
"Logprobs is not enabled for models/gemini-2.5-flash". The two ways to get a
per-field score out of it anyway -- asking the model to self-report one
alongside each value, or sampling each card N times and using per-field
agreement -- both change the prompt or the cost model, so neither is done
here. They are worth building only if the accuracy number makes Gemini a real
candidate.
"""

from __future__ import annotations

import json
import mimetypes
import os
import time
from pathlib import Path

from json_extraction import EXTRACTION_PROMPT, parse_json_fields

from extraction.base import ExtractionResult
from extraction.field_schema import build_extraction_prompt_schema

DEFAULT_MODEL = "gemini-3.6-flash"

# USD per million tokens (input, output). Thought tokens bill at the output
# rate. Only models we have actually priced go in here -- an unlisted model
# reports cost_usd=None rather than a made-up number.
PRICE_PER_MTOK = {
    # 3.6 and 3.7 Flash are $0.75/$3.75 promotional through 2026-12-31, then
    # $1.50/$7.50 -- a run costed before new year is half what the same run
    # costs after it.
    "gemini-3.6-flash": (0.75, 3.75),
    "gemini-3.7-flash": (0.75, 3.75),
    "gemini-3.5-flash": (1.50, 9.00),
    "gemini-3.5-flash-lite": (0.30, 2.50),
    "gemini-3.1-flash-lite": (0.25, 1.50),
    "gemini-3.1-pro-preview": (2.00, 12.00),
}

# Free tier is ~10-15 RPM, so --workers above 2 will spend most of its time in
# backoff. Paid tier 1 is far higher and does not need this.
RATE_LIMIT_BACKOFF_SECONDS = 30

# Worth another attempt, and they need different waits. A 429 is our own quota
# and clears on the minute boundary; a 503 is Google's capacity and clears in
# seconds, so backing off 30s for one wastes the run. Anything else -- 400 bad
# request, 404 retired model, 403 bad key -- is our problem and retrying it
# just triples the time to the error message.
RETRYABLE = {
    "429": RATE_LIMIT_BACKOFF_SECONDS,
    "RESOURCE_EXHAUSTED": RATE_LIMIT_BACKOFF_SECONDS,
    "503": 5,
    "UNAVAILABLE": 5,
    "500": 5,
    "INTERNAL": 5,
}


def _retry_wait(error: Exception, attempt: int) -> float | None:
    """Seconds to wait before retrying this error, or None if it is terminal."""
    text = str(error)
    waits = [base for marker, base in RETRYABLE.items() if marker in text]
    return max(waits) * attempt if waits else None


def batch_prompt(count: int) -> str:
    """Ask for ``count`` cards in one request, keyed "1".."count".

    Built from the same schema builder ``EXTRACTION_PROMPT`` uses, so the
    batched and single-card arms can never drift into asking for different
    fields -- which would make their accuracies incomparable.
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
        "Read each card independently and completely. Give every value as a "
        "JSON string, copied exactly as written, keeping any leading zeros "
        '("04", not 4). Use null where no code is written.\n\n' + schema
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
        # Resolved once, at construction, and used as the results directory
        # name. It has to carry the model id: every Gemini model shares the one
        # "gemini" CLI key, so a flat name means running 3.5-flash silently
        # overwrites 3.6-flash's saved output and its results.csv -- and on a
        # 20-request daily cap, output you overwrote is output you cannot
        # cheaply get back.
        self.name = os.environ.get("GEMINI_MODEL", DEFAULT_MODEL)

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

        Duck-typed rather than added to the Extractor protocol: only hosted
        models where requests-per-day is the binding limit have any reason to
        batch, and run_benchmark looks for this method rather than requiring it.

        Measured on 2026-09-02: gemini-3.5-flash batches 5 cards at no accuracy
        cost, gemini-3.5-flash-lite loses 23 points because it stops reading
        after ~3 and returns fabricated-but-well-formed values for the rest.
        The tell is output tokens per card collapsing against the single-card
        baseline, so ``cost_usd`` here is deliberately the per-card share --
        watch it, and re-measure before trusting a new model or a bigger batch.
        """
        from google import genai

        contents: list = [batch_prompt(len(image_paths))]
        for index, path in enumerate(image_paths, start=1):
            contents += [f"CARD {index}:", self._part(path)]

        client = genai.Client()
        response = _call_with_retry(
            lambda: client.models.generate_content(
                model=self.name, contents=contents, config=self._config()
            )
        )
        raw = response.text or ""
        try:
            outer = json.loads(raw[raw.index("{") : raw.rindex("}") + 1])
        except (ValueError, json.JSONDecodeError):
            outer = {}

        share = _cost_usd(self.name, response.usage_metadata)
        results = []
        for index in range(1, len(image_paths) + 1):
            card = outer.get(str(index))
            # Round-trip through parse_json_fields so a batched card gets the
            # same null/float coercion a single-card one does. A slot the model
            # omitted becomes {}, which scores as the failure it is.
            text = json.dumps(card) if card is not None else ""
            results.append(
                ExtractionResult(
                    fields=parse_json_fields(text) or {},
                    raw_text=text,
                    cost_usd=share / len(image_paths) if share is not None else None,
                )
            )
        return results

    def extract(self, image_path: Path) -> ExtractionResult:
        from google import genai

        model = self.name
        contents = [self._part(image_path), EXTRACTION_PROMPT]
        config = self._config()

        client = genai.Client()  # reads GEMINI_API_KEY
        response = self._generate(client, model, contents, config)
        raw_output = response.text or ""
        return ExtractionResult(
            fields=parse_json_fields(raw_output) or {},
            raw_text=raw_output,
            cost_usd=_cost_usd(model, response.usage_metadata),
        )

    @staticmethod
    def _generate(client, model, contents, config, attempts: int = 3):
        """Retry on throttling and on a response with no usable JSON in it.

        The second case is the one worth spending a retry on: a card that is
        mostly empty cells scores ~70% against an empty field dict, so banking
        a failed parse would read as a near-pass rather than a failure.
        """
        last_error: Exception | None = None
        for attempt in range(1, attempts + 1):
            try:
                response = client.models.generate_content(
                    model=model, contents=contents, config=config
                )
            except Exception as error:  # SDK error types vary by transport
                wait = _retry_wait(error, attempt)
                if wait is None:
                    raise
                last_error = error
                time.sleep(wait)
                continue
            if parse_json_fields(response.text) is not None:
                return response
            # Usually thinking ate the output budget (finish_reason MAX_TOKENS)
            # and the JSON is cut off past what _repair_truncated_object can
            # salvage; occasionally a safety block leaves text empty.
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

    Thinking tokens are reported separately from the response tokens and bill
    at the output rate, so they are added rather than assumed to be included.
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

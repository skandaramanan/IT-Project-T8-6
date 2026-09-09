"""Gemini: hosted multimodal LLM, prompted directly against the field schema.

Unlike Azure Document Intelligence this needs no training step -- it takes the
same ``EXTRACTION_PROMPT`` every VLM candidate gets, so its number is directly
comparable to ox-alpha's rather than to a model fitted on six labelled cards.

Four knobs, all env vars because ``run_benchmark.py`` constructs extractors
with no arguments:

    GEMINI_API_KEY              from https://aistudio.google.com/apikey
    GEMINI_MODEL                default gemini-3.6-flash
    GEMINI_MEDIA_RESOLUTION     low | medium | high; unset = the model's default
    GEMINI_CONFIDENCE_BAND      1 to have the model self-report low/medium/high
                                per field; off by default

Default model is gemini-3.5-flash-lite, and the reason is throughput rather
than accuracy. The free-tier daily cap is **per model, not per tier**: Flash is
20 requests/day/key, Flash-Lite is 500. Across five team keys that is 100/day
against 2,500/day -- so a single pass over ~6,500 cards is 65 days on Flash and
2.6 days on Flash-Lite. Measured on the 30-card benchmark, Flash-Lite reads
91.3% of coded fields against Flash's 93.7%, so 2.4 points buys the only
configuration that can process the corpus at all. Set GEMINI_MODEL to override.

(The OCR spike's "-23 points" for Flash-Lite was a *batched* run, where it stops
reading after ~3 cards and fabricates the rest. Single-card it is fine.)

Pro-class models left the free tier on 2026-04-01 and the $300 Google Cloud
trial credit has excluded Gemini API usage since March 2026, so Flash-class is
the whole free menu. gemini-3.6-flash is the named replacement for
gemini-2.5-flash, which ``models.list`` still advertises but which 404s for keys
created after its retirement -- listing a model is not the same as being able to
call it, so check by calling.

Prompts may be used to improve Google's products -- fine for 30 benchmark cards
already in a shared Drive, not fine for the archive. Check your live numbers at
https://aistudio.google.com/rate-limit.

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
"Logprobs is not enabled for models/gemini-2.5-flash". Two ways round that were
noted here as worth building only once the accuracy number made Gemini a real
candidate: asking the model to self-report a band alongside each value, or
sampling each card N times and using per-field agreement.

D012 made it the candidate, so the first is now built, behind
``GEMINI_CONFIDENCE_BAND``. It is off by default because it is a **different
prompt** and therefore a different experiment: turning it on changes what the
model is asked and could move its accuracy either way, and every raw response
saved under the plain prompt would stop being comparable. Banded runs file
themselves under ``<model>-banded`` so both sit side by side and IT-100 can
report what the band costs.

``confidence`` on ``ExtractionResult`` stays None even when banded. The band is
a **category**, not a number, and turning "high" into 0.9 is IT-99's decision,
not this adapter's -- writing a number here would quietly pre-empt it. The band
survives in ``raw_text`` instead, which is preserved verbatim and travels with
the raw/ directory; ``json_extraction.parse_confidence_bands`` reads it back.

The batched path follows ``self.banded`` too, via ``banded_batch_prompt`` --
same per-field ``{"value": ..., "confidence": ...}`` shape as the single-card
banded prompt, just keyed "1".."count" like the flat batch prompt. Results
still file under ``<model>-banded`` regardless of batch size, same as the
single-card path; keeping different batch sizes apart on disk is the caller's
job (``run_benchmark.py --results-root``), same as it already is for the
unbanded batched runs. Batching and banding have still never been *measured*
together -- this only makes asking for both possible, not validated; re-run
batch_probe-style before trusting a banded batch's numbers.
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
    parse_json_fields,
)

from extraction.base import ExtractionResult
from extraction.field_schema import build_extraction_prompt_schema

DEFAULT_MODEL = "gemini-3.5-flash-lite"

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
    """Seconds to wait before retrying this error, or None if it is terminal.

    Markers are matched on word boundaries, not as bare substrings. A plain
    ``"500" in text`` also fires on any message that happens to contain those
    digits -- ``400 INVALID_ARGUMENT: The input token count (1500) exceeds ...``
    is terminal, and treating it as a 500 spends three attempts and a minute of
    backoff before showing the one line worth reading.
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


def _parse_batch_object(raw: str) -> dict:
    """The ``{"1": {...}, "2": {...}}`` object out of a batched response.

    Anything else -- no JSON at all, or JSON that is a list or a bare string --
    is an empty batch, not an exception: a model that answered with a list would
    otherwise take down every card in the request at ``outer.get``.
    """
    try:
        parsed = json.loads(raw[raw.index("{") : raw.rindex("}") + 1])
    except (ValueError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def banded_batch_prompt(count: int) -> str:
    """``batch_prompt``, but each card's field object holds ``{"value": ...,
    "confidence": ...}`` pairs instead of bare values -- the batched form of
    ``json_extraction.BANDED_EXTRACTION_PROMPT``. Same schema builder and same
    per-card keying, so a banded batch is comparable to an unbanded one on
    everything except the one thing being asked for differently.
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
        '<"low"|"medium"|"high">}.\n\n'
        "Read each card independently and completely. Give every code as a "
        'JSON string, copied exactly as written, keeping any leading zeros ("04", '
        "not 4). Use null as the value where no code is written.\n\n"
        'Judge confidence on how clearly you can read that cell: "high" if the '
        'digits are unambiguous, "medium" if you had to choose between plausible '
        'readings, "low" if the cell is faint, damaged, overwritten or a guess. '
        "Say low when it is low -- a wrong value marked high is worse than an "
        "honest one marked low, because a reviewer will never look at it.\n\n" + schema
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
        # Two names, and conflating them is the bug this splits apart: model_id
        # is what the API is called with, name is what results are filed under.
        self.model_id = os.environ.get("GEMINI_MODEL", DEFAULT_MODEL)
        self.name = self.model_id
        # GEMINI_CONFIDENCE_BAND asks the model to say how sure it is of each
        # value (see json_extraction.BANDED_EXTRACTION_PROMPT). It is a
        # different prompt, so it is a different run: the name carries the
        # suffix for the same reason it carries the model id, and results from
        # the two prompts stay side by side instead of one overwriting the
        # other. Comparing them is how we learn what the band costs.
        self.banded = os.environ.get("GEMINI_CONFIDENCE_BAND", "").strip().lower() in (
            "1",
            "true",
            "yes",
        )
        if self.banded:
            self.name += "-banded"

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

        Follows ``self.banded`` the same way ``extract`` does: banded_batch_
        prompt when set, so a banded run stays banded across the batch/single
        split rather than silently dropping bands the moment ``--batch`` is
        passed.
        """
        from google import genai

        prompt = banded_batch_prompt if self.banded else batch_prompt
        contents: list = [prompt(len(image_paths))]
        for index, path in enumerate(image_paths, start=1):
            contents += [f"CARD {index}:", self._part(path)]

        client = genai.Client()
        # Retry an unusable answer, the same way _generate does for a single
        # card: a response that parses to nothing costs the whole batch, so
        # banking the first one makes the batched arm look worse than the model
        # is for reasons that have nothing to do with batching. The last
        # response is kept either way -- raw_text and cost_usd still get
        # recorded, and the empty batch scores as the failure it is.
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
        )

    @staticmethod
    def _generate(client, model, contents, config, attempts: int = 3):
        """Retry on throttling and on a response with no usable JSON in it.

        The second case is the one worth spending a retry on: a card that is
        mostly empty cells scores ~70% against an empty field dict, so banking
        a failed parse would read as a near-pass rather than a failure.

        A model that answered and kept answering unusably is **returned, not
        raised**, once the retries are spent. Raising wrote no raw file, and the
        harness treats an absent raw file as a card never attempted -- so every
        later run re-bought that card at three requests each, converged on the
        same unusable answer, and never recorded what it said. Returning it
        saves the response, scores it as the miss it is, and lets the pairing
        report it as ``unparseable`` rather than silently unread. Only a call
        that never came back at all still raises.
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
                # Sleeping after the final attempt buys nothing: the outcome is
                # already decided, and at 30s x 3 that is 90 seconds per card of
                # dead wall time on a throttled run.
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

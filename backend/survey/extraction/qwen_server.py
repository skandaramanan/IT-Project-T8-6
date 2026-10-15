"""Qwen2.5-VL served over an OpenAI-compatible API (LM Studio, llama.cpp).

The same model and prompt as ``qwen.py``, for a machine that can't run
bitsandbytes: it needs CUDA, so an AMD card (or Windows without WSL CUDA)
can't load the 4-bit transformers path. A local server loads a GGUF quant on
whatever GPU it supports and this talks to it over HTTP.

Env vars, because ``run_benchmark.py`` constructs extractors with no args:

    QWEN_SERVER_URL     default http://localhost:1234/v1 (LM Studio's default)
    QWEN_SERVER_MODEL   the model id the server lists under /v1/models;
                        blank = the only one loaded
    QWEN_STRUCK_DETECTION
                        1 to also report which printed options are struck
                        through (FR-06, D023); off by default. A different
                        prompt, so a different experiment: readings file
                        under ``<name>-struck``
    QWEN_REPEAT_PENALTY blank = 1.05, what the model's own generation_config.json
                        sets and the calibration ran with
    QWEN_MAX_PIXELS     pixel budget per card; blank = qwen.MAX_PIXELS, the
                        ~1MP the calibration was measured at. 0 = native size.
                        IT-124's corpus run used 2000000 (D019)

Decoding is pinned greedy (top-k 1, no top-p/min-p) on every request. Left
unset, LM Studio applies its own sampler presets to API calls, and on the 8
worst benchmark cards that cost 80 of 489 coded fields against the same model
decoded greedily (310 against 390). qwen.py gets this for free: transformers
reads the model's generation_config.json, which is greedy with a 1.05 repeat
penalty.

Not the calibrated configuration. D016's constants were measured on the
bitsandbytes 4-bit build at ~1MP; ``model_id`` is still ``qwen2.5-vl`` so its
tables apply. IT-124 checked that on the 30 benchmark cards (D019, 2026-10-16):
Q6_K at 2MP reads 84.1% of coded fields against the 4-bit build's 75.0%, and
``agree`` holds (97.6% against 0.97) while ``disagree`` and ``one_blank`` come
in about 0.1 under their constants. Only ``agree`` clears review (D022), so
routing is unchanged. Rerun ``benchmark/run_benchmark.py --model
qwen2.5-vl-server`` before trusting any other quant or pixel budget.

A reply cut off at MAX_TOKENS raises rather than returning the partial fields
its JSON repairs to, so it is never cached; a dropped connection, timeout or
5xx is tried again.

The image is resized here, to QWEN_MAX_PIXELS at multiples of 28 like
qwen_vl_utils does, rather than left to the server, so the resolution a reading
was made at is the one we chose. Above the default it is a different
experiment -- better digits, maybe, but a picture D016 never saw, and the
vision encoder's full-attention layers grow with the square of the pixel count
(uncapped, the T4 run OOM'd at ~19GB) -- so those readings file under
``<name>-<pixels>px`` and a changed budget never replays another's cache.
"""

from __future__ import annotations

import base64
import io
import json
import math
import os
import time
import urllib.error
import urllib.request
from pathlib import Path

from survey.extraction.base import ExtractionResult
from survey.extraction.json_extraction import (
    EXTRACTION_PROMPT,
    STRUCK_EXTRACTION_PROMPT,
    parse_json_fields,
    parse_struck_fields,
)
from survey.extraction.qwen import MAX_PIXELS

DEFAULT_URL = "http://localhost:1234/v1"

# Qwen2.5-VL-7B-Instruct's generation_config.json: what qwen.py's generate()
# inherited when the calibration readings were made.
DEFAULT_REPEAT_PENALTY = 1.05

# Image tokens are 28x28 patches; qwen_vl_utils rounds each side to a multiple.
PATCH = 28

# A card takes tens of seconds on a consumer GPU; the first one also waits for
# the server to load the model.
TIMEOUT_S = 600

# A reply this long is cut off, not finished (see extract()).
MAX_TOKENS = 2048

# A dropped connection, a timeout or a 5xx is the server, not the card: try
# again, as gemini._call_with_retry does. A 4xx is the request's fault, and
# sending it again gets the same answer.
ATTEMPTS = 3
RETRY_WAIT_S = 5


def _env_number(name: str, default, cast):
    """An env var read as a number; blank is the default. A typo ("2MP") is
    named, rather than surfacing as a bare ValueError from int()."""
    raw = (os.environ.get(name) or "").strip()
    if not raw:
        return default
    try:
        return cast(raw)
    except ValueError:
        raise ValueError(
            f"{name}={raw!r} is not a {cast.__name__}; leave it blank for {default}"
        ) from None


def _retryable(error: Exception) -> bool:
    if isinstance(error, urllib.error.HTTPError):
        return error.code >= 500
    return isinstance(error, (urllib.error.URLError, TimeoutError, ConnectionError))


def fit_to_max_pixels(
    width: int, height: int, max_pixels: int = MAX_PIXELS
) -> tuple[int, int]:
    """qwen_vl_utils.smart_resize's upper bound: under max_pixels (0 = no
    bound), sides % 28 == 0."""
    scale = min(1.0, math.sqrt(max_pixels / (width * height))) if max_pixels else 1.0
    return (
        max(PATCH, math.floor(width * scale / PATCH) * PATCH),
        max(PATCH, math.floor(height * scale / PATCH) * PATCH),
    )


def _image_data_url(image_path: Path, max_pixels: int) -> str:
    from PIL import Image

    with Image.open(image_path) as image:
        image = image.convert("RGB")
        image = image.resize(
            fit_to_max_pixels(*image.size, max_pixels), Image.Resampling.BICUBIC
        )
        buffer = io.BytesIO()
        # Lossless: the server would decode a JPEG back to these pixels anyway,
        # and recompressing pencil digits is a loss the calibration never had.
        image.save(buffer, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode()


class QwenServerExtractor:
    # The pipeline keys D016's confidence tables on this, not on ``name``.
    model_id = "qwen2.5-vl"

    def __init__(self) -> None:
        self.base_url = (os.environ.get("QWEN_SERVER_URL") or DEFAULT_URL).rstrip("/")
        self.model = os.environ.get("QWEN_SERVER_MODEL") or None
        self.max_pixels = _env_number("QWEN_MAX_PIXELS", MAX_PIXELS, int)
        self.repeat_penalty = _env_number(
            "QWEN_REPEAT_PENALTY", DEFAULT_REPEAT_PENALTY, float
        )
        self.struck_detection = os.environ.get(
            "QWEN_STRUCK_DETECTION", ""
        ).strip().lower() in (
            "1",
            "true",
            "yes",
        )
        # ``name`` is the cache folder: a reading is only replayed at the
        # resolution it was made at.
        self.name = "qwen2.5-vl-server"
        if self.max_pixels != MAX_PIXELS:
            self.name += f"-{self.max_pixels or 'native'}px"
        if self.repeat_penalty != DEFAULT_REPEAT_PENALTY:
            self.name += f"-rp{self.repeat_penalty:g}"
        if self.struck_detection:
            self.name += "-struck"

    def _get(self, path: str) -> dict:
        with urllib.request.urlopen(self.base_url + path, timeout=10) as response:
            return json.load(response)

    def is_available(self) -> bool:
        try:
            models = [m["id"] for m in self._get("/models").get("data", [])]
        except (OSError, ValueError):
            return False
        if self.model is None:
            # Guessing between several would silently run the wrong one.
            if len(models) != 1:
                return False
            self.model = models[0]
        return self.model in models

    def _post(self, request: urllib.request.Request) -> dict:
        for attempt in range(1, ATTEMPTS + 1):
            try:
                with urllib.request.urlopen(request, timeout=TIMEOUT_S) as response:
                    return json.load(response)
            except Exception as error:
                if attempt < ATTEMPTS and _retryable(error):
                    time.sleep(RETRY_WAIT_S * attempt)
                    continue
                if not isinstance(error, urllib.error.HTTPError):
                    raise
                # The status alone ("400 Bad Request") hides why; the body says.
                raise RuntimeError(
                    f"{error}: {error.read().decode(errors='replace')}"
                ) from None
        raise AssertionError("unreachable")

    def extract(self, image_path: Path) -> ExtractionResult:
        body = {
            "model": self.model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": _image_data_url(image_path, self.max_pixels)
                            },
                        },
                        {
                            "type": "text",
                            "text": STRUCK_EXTRACTION_PROMPT
                            if self.struck_detection
                            else EXTRACTION_PROMPT,
                        },
                    ],
                }
            ],
            # qwen.py's model.generate() is greedy with this cap. Every sampler
            # is named: the server's own presets apply to any left out.
            "temperature": 0,
            "top_k": 1,
            "top_p": 1,
            "min_p": 0,
            "repeat_penalty": self.repeat_penalty,
            "max_tokens": MAX_TOKENS,
        }
        request = urllib.request.Request(
            self.base_url + "/chat/completions",
            data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json"},
        )
        reply = self._post(request)
        choice = reply["choices"][0]
        raw_output = choice["message"]["content"] or ""
        # Cut off at MAX_TOKENS, the JSON is repaired into a partial field set
        # (json_extraction._repair_truncated_object) that looks like a reading.
        # Returned, the pipeline would cache it and every rerun replay it, with
        # the missing fields never reported. Raising leaves nothing cached.
        if choice.get("finish_reason") == "length":
            raise RuntimeError(
                f"reply cut off at {MAX_TOKENS} tokens, not cached: "
                f"...{raw_output[-80:]!r}"
            )

        fields = parse_json_fields(raw_output) or {}
        return ExtractionResult(
            fields=fields,
            raw_text=raw_output,
            # None, not {}, when detection did not run: "no strikes found" and
            # "nobody looked" are different claims (record.build_field)
            struck=parse_struck_fields(raw_output) if self.struck_detection else None,
        )

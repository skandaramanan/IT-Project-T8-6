"""Ox Alpha (OpenRouter stealth model): hosted reasoning VLM, OpenAI-compatible.

Routed through OpenRouter (https://openrouter.ai, model id ``stealth/ox-alpha``).
Multimodal: accepts the card image as a base64 data URL in an ``image_url``
content part. Uses only the standard library -- no SDK dependency added.

Set OPENROUTER_API_KEY (OpenRouter dashboard) and the runner picks it up.
"""

from __future__ import annotations

import base64
import json
import mimetypes
import os
import time
import urllib.error
import urllib.request
from pathlib import Path

from json_extraction import EXTRACTION_PROMPT, parse_json_fields

from extraction.base import ExtractionResult

MODEL_ID = "stealth/ox-alpha"
API_URL = "https://openrouter.ai/api/v1/chat/completions"
TIMEOUT_SECONDS = 300  # p99 latency for this model is minutes, not seconds
# Reasoning tokens count against max_tokens; a typical card burns ~6.5k
# (reasoning + JSON). 8192 left runs that reason longer truncated mid-JSON,
# which parsed as zero fields and scored 0%.
MAX_TOKENS = 16384
# Backoff for an upstream 429. stealth/ox-alpha runs on a shared free pool, so
# throttling is a wait-your-turn queue rather than a failure -- 60/120/180s.
RATE_LIMIT_BACKOFF_SECONDS = 60


class OxAlphaExtractor:
    name = "ox-alpha"

    def is_available(self) -> bool:
        return bool(os.environ.get("OPENROUTER_API_KEY"))

    def extract(self, image_path: Path) -> ExtractionResult:
        payload = {
            "model": MODEL_ID,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": EXTRACTION_PROMPT},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": self._image_data_url(image_path),
                            },
                        },
                    ],
                }
            ],
            "max_tokens": MAX_TOKENS,
        }

        raw_output = self._post(payload)
        fields = parse_json_fields(raw_output) or {}
        return ExtractionResult(fields=fields, raw_text=raw_output)

    @staticmethod
    def _image_data_url(image_path: Path) -> str:
        mime = mimetypes.types_map.get(image_path.suffix.lower(), "image/jpeg")
        encoded = base64.b64encode(image_path.read_bytes()).decode("ascii")
        return f"data:{mime};base64,{encoded}"

    @staticmethod
    def _post(payload: dict, attempts: int = 3) -> str:
        last_error: Exception | None = None
        for attempt in range(1, attempts + 1):
            request = urllib.request.Request(
                API_URL,
                data=json.dumps(payload).encode("utf-8"),
                headers={
                    "Authorization": f"Bearer {os.environ['OPENROUTER_API_KEY']}",
                    "Content-Type": "application/json",
                },
                method="POST",
            )
            try:
                with urllib.request.urlopen(
                    request, timeout=TIMEOUT_SECONDS
                ) as response:
                    body = json.loads(response.read().decode("utf-8"))
            except urllib.error.HTTPError as error:
                detail = error.read().decode("utf-8", errors="replace")
                # OpenRouter wraps an upstream provider failure as 400 with a
                # "provider_name" in metadata (body is just {"raw":"ERROR"}).
                # That is transient and worth retrying; a 400 without it is our
                # request being malformed, which retrying can't fix.
                upstream_400 = error.code == 400 and "provider_name" in detail
                if error.code == 429 or 500 <= error.code < 600 or upstream_400:
                    last_error = RuntimeError(
                        f"Ox Alpha API returned {error.code}: {detail}"
                    )
                    # 429 here is the free model's shared upstream pool, which
                    # clears in minutes, not seconds -- 2/4/8s just burns the
                    # three attempts and reports a failure that was a queue.
                    time.sleep(
                        RATE_LIMIT_BACKOFF_SECONDS * attempt
                        if error.code == 429
                        else 2**attempt
                    )
                    continue
                raise RuntimeError(
                    f"Ox Alpha API returned {error.code}: {detail}"
                ) from error
            except urllib.error.URLError as error:
                last_error = RuntimeError(f"Ox Alpha API unreachable: {error.reason}")
                time.sleep(2**attempt)
                continue

            message = body["choices"][0]["message"]
            # Reasoning models can return content=None when reasoning ate the
            # whole token budget (or the provider filtered the response).
            content = message.get("content") or ""
            finish_reason = body["choices"][0].get("finish_reason")
            if isinstance(content, str) and content.strip():
                if parse_json_fields(content) is None:
                    # Nothing usable in there: truncated mid-JSON
                    # (finish_reason="length"), prose with no JSON in it, or a
                    # placeholder object with none of the schema's keys. Retry
                    # rather than hand scoring an empty field dict -- on a card
                    # that is mostly empty cells, empty scores deceptively well.
                    last_error = RuntimeError(
                        f"Ox Alpha returned no usable JSON (finish_reason={finish_reason!r})"
                    )
                    time.sleep(2**attempt)
                    continue
                return content
            last_error = RuntimeError(
                f"Ox Alpha returned empty content (finish_reason={finish_reason!r})"
            )
            time.sleep(2**attempt)
        assert last_error is not None
        raise last_error

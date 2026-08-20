"""Pixtral (Mistral): Apache-2.0 VLM, prompted against the field schema.

Runs on vLLM, not transformers -- a genuinely different serving stack from
every other adapter here. Needs `vllm` (>=0.6.2) and `mistral_common`
(>=1.4.4), neither resolved into uv.lock from here; add them and re-run
`uv lock` on the machine that'll actually run this. Also needs a real GPU.
"""

from __future__ import annotations

from pathlib import Path

from json_extraction import EXTRACTION_PROMPT, parse_json_fields

from extraction.base import ExtractionResult

MODEL_ID = "mistralai/Pixtral-12B-2409"


class PixtralExtractor:
    name = "pixtral"

    def __init__(self) -> None:
        self._llm = None

    def is_available(self) -> bool:
        try:
            import mistral_common  # noqa: F401
            import vllm  # noqa: F401
        except ImportError:
            return False
        return True

    def _load(self):
        if self._llm is None:
            from vllm import LLM

            self._llm = LLM(model=MODEL_ID, tokenizer_mode="mistral")
        return self._llm

    def extract(self, image_path: Path) -> ExtractionResult:
        from vllm.sampling_params import SamplingParams

        llm = self._load()

        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": EXTRACTION_PROMPT},
                    {
                        "type": "image_url",
                        "image_url": {"url": image_path.resolve().as_uri()},
                    },
                ],
            }
        ]
        outputs = llm.chat(messages, sampling_params=SamplingParams(max_tokens=2048))
        raw_output = outputs[0].outputs[0].text

        fields = parse_json_fields(raw_output) or {}
        return ExtractionResult(fields=fields, raw_text=raw_output)

"""NuExtract3: purpose-built structured-extraction VLM (4B) -- not a general
VLM prompted to produce JSON, but a model designed around exactly this
template-in/JSON-out shape.

Unlike every other adapter here, the schema isn't embedded in a text prompt
-- it's passed as a literal JSON template (field name -> type string) via
the ``template`` chat-template kwarg, and the model fills it in directly.
All 60 fields are typed "verbatim-string" here; NuExtract's template syntax
supports richer per-field types (enums, dates, numbers) that could use
extraction.field_schema's ``kind``/``code_book_category`` for a tighter
template, not done in this first pass.

Needs a real GPU. torch/transformers aren't resolved into uv.lock from here;
add them and re-run `uv lock` on the machine that'll actually run this.
"""

from __future__ import annotations

import json
from pathlib import Path

from json_extraction import parse_json_fields

from extraction.base import ExtractionResult
from extraction.field_schema import FIELD_SCHEMA

MODEL_ID = "numind/NuExtract3"

TEMPLATE = json.dumps({spec.name: "verbatim-string" for spec in FIELD_SCHEMA}, indent=4)


class NuExtractExtractor:
    name = "nuextract3"

    def __init__(self) -> None:
        self._model = None
        self._processor = None

    def is_available(self) -> bool:
        try:
            import bitsandbytes  # noqa: F401
            import torch  # noqa: F401
            import transformers  # noqa: F401
        except ImportError:
            return False
        return True

    def _load(self):
        if self._model is None:
            import torch
            from transformers import AutoModelForImageTextToText, AutoProcessor, BitsAndBytesConfig

            bnb_config = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_compute_dtype=torch.bfloat16)
            self._processor = AutoProcessor.from_pretrained(
                MODEL_ID, trust_remote_code=True
            )
            self._model = AutoModelForImageTextToText.from_pretrained(
                MODEL_ID,
                quantization_config=bnb_config,
                device_map="auto",
                trust_remote_code=True,
            ).eval()
        return self._model, self._processor

    def extract(self, image_path: Path) -> ExtractionResult:
        import torch

        from json_extraction import load_image_for_vram

        model, processor = self._load()

        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "image", "image": load_image_for_vram(image_path)}
                ],
            }
        ]
        inputs = processor.apply_chat_template(
            messages,
            add_generation_prompt=True,
            tokenize=True,
            return_dict=True,
            return_tensors="pt",
            template=TEMPLATE,
            enable_thinking=False,
        ).to(model.device)

        with torch.inference_mode():
            generated_ids = model.generate(
                **inputs, max_new_tokens=4096, do_sample=False
            )
        generated_ids = generated_ids[:, inputs.input_ids.shape[1] :]
        raw_output = processor.batch_decode(
            generated_ids, skip_special_tokens=True, clean_up_tokenization_spaces=False
        )[0].strip()

        fields = parse_json_fields(raw_output) or {}
        return ExtractionResult(fields=fields, raw_text=raw_output)

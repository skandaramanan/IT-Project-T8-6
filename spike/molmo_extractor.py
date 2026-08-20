"""Molmo: fully open (weights and training data) VLM, prompted against the
field schema.

Different API shape again -- ``processor.process()`` (not the usual
``processor()`` call) and ``model.generate_from_batch()`` (not
``model.generate()``).

Needs a real GPU. torch/transformers aren't resolved into uv.lock from here;
add them and re-run `uv lock` on the machine that'll actually run this.
"""

from __future__ import annotations

from pathlib import Path

from json_extraction import EXTRACTION_PROMPT, parse_json_fields

from extraction.base import ExtractionResult

MODEL_ID = "allenai/Molmo-7B-D-0924"


class MolmoExtractor:
    name = "molmo"

    def __init__(self) -> None:
        self._model = None
        self._processor = None

    def is_available(self) -> bool:
        try:
            import torch  # noqa: F401
            import transformers  # noqa: F401
        except ImportError:
            return False
        return True

    def _load(self):
        if self._model is None:
            from transformers import AutoModelForCausalLM, AutoProcessor

            self._processor = AutoProcessor.from_pretrained(
                MODEL_ID, trust_remote_code=True, torch_dtype="auto", device_map="auto"
            )
            self._model = AutoModelForCausalLM.from_pretrained(
                MODEL_ID, trust_remote_code=True, torch_dtype="auto", device_map="auto"
            )
        return self._model, self._processor

    def extract(self, image_path: Path) -> ExtractionResult:
        from PIL import Image
        from transformers import GenerationConfig

        model, processor = self._load()

        inputs = processor.process(
            images=[Image.open(image_path).convert("RGB")], text=EXTRACTION_PROMPT
        )
        inputs = {k: v.to(model.device).unsqueeze(0) for k, v in inputs.items()}

        output = model.generate_from_batch(
            inputs,
            GenerationConfig(max_new_tokens=2048, stop_strings="<|endoftext|>"),
            tokenizer=processor.tokenizer,
        )
        generated_tokens = output[0, inputs["input_ids"].size(1) :]
        raw_output = processor.tokenizer.decode(
            generated_tokens, skip_special_tokens=True
        )

        fields = parse_json_fields(raw_output) or {}
        return ExtractionResult(fields=fields, raw_text=raw_output)

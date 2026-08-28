"""Qwen3-VL: successor to Qwen2.5-VL, same prompt-against-schema approach.

Simpler pipeline than Qwen2.5-VL -- ``apply_chat_template`` tokenizes and
processes the image directly, no separate ``qwen_vl_utils.process_vision_info``
step needed.

Needs a real GPU. torch/transformers aren't resolved into uv.lock from here;
add them and re-run `uv lock` on the machine that'll actually run this.
"""

from __future__ import annotations

from pathlib import Path

from json_extraction import EXTRACTION_PROMPT, parse_json_fields

from extraction.base import ExtractionResult

MODEL_ID = "Qwen/Qwen3-VL-8B-Instruct"


class Qwen3VLExtractor:
    name = "qwen3-vl"

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
            from transformers import AutoProcessor, BitsAndBytesConfig, Qwen3VLForConditionalGeneration

            bnb_config = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_compute_dtype=torch.bfloat16)
            self._model = Qwen3VLForConditionalGeneration.from_pretrained(
                MODEL_ID, quantization_config=bnb_config, device_map="auto"
            )
            self._processor = AutoProcessor.from_pretrained(MODEL_ID)
        return self._model, self._processor

    def extract(self, image_path: Path) -> ExtractionResult:
        from json_extraction import load_image_for_vram

        model, processor = self._load()

        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "image", "image": load_image_for_vram(image_path)},
                    {"type": "text", "text": EXTRACTION_PROMPT},
                ],
            }
        ]
        inputs = processor.apply_chat_template(
            messages,
            tokenize=True,
            add_generation_prompt=True,
            return_dict=True,
            return_tensors="pt",
        ).to(model.device)

        generated_ids = model.generate(**inputs, max_new_tokens=2048)
        trimmed = [out[len(inp) :] for inp, out in zip(inputs.input_ids, generated_ids)]
        raw_output = processor.batch_decode(
            trimmed, skip_special_tokens=True, clean_up_tokenization_spaces=False
        )[0]

        fields = parse_json_fields(raw_output) or {}
        return ExtractionResult(fields=fields, raw_text=raw_output)

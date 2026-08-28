"""Qwen2.5-VL: open-weight VLM, prompted directly against the field schema.

The prompt embeds extraction.field_schema's 60-field block and asks for a
JSON object keyed by those exact field names. A response that isn't valid
JSON scores as an empty ``fields`` dict; ``raw_text`` still carries what the
model actually said, for debugging.

Needs a real GPU -- not meant to run on this laptop. torch/transformers/
qwen_vl_utils aren't resolved into uv.lock from here (disk-constrained
machine, wrong target anyway); add them and re-run `uv lock` on the machine
that'll actually run this. As of the model's HF card, Qwen2_5_VLForCondition-
alGeneration may need transformers installed from source rather than the
latest PyPI release -- check before assuming a plain `uv add transformers`
is enough.
"""

from __future__ import annotations

from pathlib import Path

from json_extraction import EXTRACTION_PROMPT, parse_json_fields

from extraction.base import ExtractionResult

MODEL_ID = "Qwen/Qwen2.5-VL-7B-Instruct"


class QwenVLExtractor:
    name = "qwen2.5-vl"

    def __init__(self) -> None:
        self._model = None
        self._processor = None

    def is_available(self) -> bool:
        try:
            import bitsandbytes  # noqa: F401
            import qwen_vl_utils  # noqa: F401
            import torch  # noqa: F401
            import transformers  # noqa: F401
        except ImportError:
            return False
        return True

    def _load(self):
        if self._model is None:
            import torch
            from transformers import AutoProcessor, BitsAndBytesConfig, Qwen2_5_VLForConditionalGeneration

            bnb_config = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_compute_dtype=torch.bfloat16)
            self._model = Qwen2_5_VLForConditionalGeneration.from_pretrained(
                MODEL_ID, quantization_config=bnb_config, device_map="auto"
            )
            self._processor = AutoProcessor.from_pretrained(MODEL_ID)
        return self._model, self._processor

    def extract(self, image_path: Path) -> ExtractionResult:
        from json_extraction import load_image_for_vram
        from qwen_vl_utils import process_vision_info

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
        text = processor.apply_chat_template(
            messages, tokenize=False, add_generation_prompt=True
        )
        image_inputs, video_inputs = process_vision_info(messages)
        inputs = processor(
            text=[text],
            images=image_inputs,
            videos=video_inputs,
            padding=True,
            return_tensors="pt",
        ).to(model.device)

        generated_ids = model.generate(**inputs, max_new_tokens=2048)
        trimmed = [out[len(inp) :] for inp, out in zip(inputs.input_ids, generated_ids)]
        raw_output = processor.batch_decode(
            trimmed, skip_special_tokens=True, clean_up_tokenization_spaces=False
        )[0]

        fields = parse_json_fields(raw_output) or {}
        return ExtractionResult(fields=fields, raw_text=raw_output)

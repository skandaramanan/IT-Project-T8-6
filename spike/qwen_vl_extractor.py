"""Qwen2.5-VL: open-weight VLM, prompted directly against the field schema.

The prompt embeds extraction.field_schema's field block and asks for a
JSON object keyed by those exact field names. A response that isn't valid
JSON scores as an empty ``fields`` dict; ``raw_text`` still carries what the
model actually said, for debugging.

Needs a real GPU -- not meant to run on this laptop. torch/transformers/
bitsandbytes/accelerate/qwen_vl_utils aren't resolved into uv.lock: locking a
CUDA stack across three platforms for the one machine that runs it costs more
than it buys, so they are installed on that machine instead. See
spike/colab_qwen_arm.ipynb, which does exactly that on a free Colab T4. As of
the model's HF card, Qwen2_5_VLForConditionalGeneration may need transformers
installed from source rather than the latest PyPI release -- check before
assuming a plain `pip install transformers` is enough.

Loaded 4-bit: the 7B weights are ~15GB at full precision, past a 12GB card and
level with a 16GB one before activations. Compute dtype follows the hardware --
bf16 needs compute capability 8.0, so an Ampere card gets it and a Turing T4,
which is what Colab's free tier hands out, gets fp16.
"""

from __future__ import annotations

from pathlib import Path

from json_extraction import EXTRACTION_PROMPT, parse_json_fields

from extraction.base import ExtractionResult

MODEL_ID = "Qwen/Qwen2.5-VL-7B-Instruct"

# Qwen counts image tokens in 28x28 units. The scans are ~9MP; uncapped, the
# vision encoder tried to allocate ~19GB of attention and OOM'd every card.
MAX_PIXELS = 1280 * 28 * 28


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
            from transformers import (
                AutoProcessor,
                BitsAndBytesConfig,
                Qwen2_5_VLForConditionalGeneration,
            )

            self._model = Qwen2_5_VLForConditionalGeneration.from_pretrained(
                MODEL_ID,
                quantization_config=BitsAndBytesConfig(
                    load_in_4bit=True,
                    bnb_4bit_compute_dtype=torch.bfloat16
                    if torch.cuda.is_bf16_supported()
                    else torch.float16,
                ),
                device_map="auto",
            )
            self._processor = AutoProcessor.from_pretrained(
                MODEL_ID, max_pixels=MAX_PIXELS
            )
        return self._model, self._processor

    def extract(self, image_path: Path) -> ExtractionResult:
        from qwen_vl_utils import process_vision_info

        model, processor = self._load()

        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "image", "image": str(image_path)},
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

"""InternVL3: MIT-licensed VLM, prompted against the field schema.

Different API shape than the Qwen models -- a custom ``model.chat()`` method
rather than ``generate()``, and image preprocessing (resize + ImageNet
normalize) done by hand rather than through a processor.

Needs a real GPU. torch/transformers/torchvision aren't resolved into
uv.lock from here; add them and re-run `uv lock` on the machine that'll
actually run this.
"""

from __future__ import annotations

from pathlib import Path

from json_extraction import EXTRACTION_PROMPT, parse_json_fields

from extraction.base import ExtractionResult

MODEL_ID = "OpenGVLab/InternVL3-8B"

IMAGENET_MEAN = (0.485, 0.456, 0.406)
IMAGENET_STD = (0.229, 0.224, 0.225)


class InternVLExtractor:
    name = "internvl3"

    def __init__(self) -> None:
        self._model = None
        self._tokenizer = None

    def is_available(self) -> bool:
        try:
            import torch  # noqa: F401
            import torchvision  # noqa: F401
            import transformers  # noqa: F401
        except ImportError:
            return False
        return True

    def _load(self):
        if self._model is None:
            import torch
            from transformers import AutoModel, AutoTokenizer

            self._model = (
                AutoModel.from_pretrained(
                    MODEL_ID,
                    torch_dtype=torch.bfloat16,
                    low_cpu_mem_usage=True,
                    use_flash_attn=True,
                    trust_remote_code=True,
                )
                .eval()
                .cuda()
            )
            self._tokenizer = AutoTokenizer.from_pretrained(
                MODEL_ID, trust_remote_code=True
            )
        return self._model, self._tokenizer

    def _pixel_values(self, image_path: Path):
        import torch
        import torchvision.transforms as T
        from PIL import Image
        from torchvision.transforms.functional import InterpolationMode

        transform = T.Compose(
            [
                T.Lambda(lambda img: img.convert("RGB") if img.mode != "RGB" else img),
                T.Resize((448, 448), interpolation=InterpolationMode.BICUBIC),
                T.ToTensor(),
                T.Normalize(mean=IMAGENET_MEAN, std=IMAGENET_STD),
            ]
        )
        image = Image.open(image_path).convert("RGB")
        return transform(image).unsqueeze(0).to(torch.bfloat16).cuda()

    def extract(self, image_path: Path) -> ExtractionResult:
        model, tokenizer = self._load()
        pixel_values = self._pixel_values(image_path)

        question = f"<image>\n{EXTRACTION_PROMPT}"
        raw_output = model.chat(
            tokenizer,
            pixel_values,
            question,
            {"max_new_tokens": 2048, "do_sample": False},
        )

        fields = parse_json_fields(raw_output) or {}
        return ExtractionResult(fields=fields, raw_text=raw_output)

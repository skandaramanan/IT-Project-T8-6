"""Baidu Unlimited-OCR: 3B, MIT-licensed, one-shot long-document parser
(GOT/DeepSeek-OCR-style ``model.infer`` API), prompted against the field schema.
Unlike the Qwen/InternVL/Molmo candidates this is a *document parser*, not a
general VLM -- it's trained to emit markdown/plain transcriptions, so it may
ignore the "return ONLY a JSON object" instruction. That's a spike finding to
record, not a bug to paper over: we prompt it with the same EXTRACTION_PROMPT as
every other adapter and let ``parse_json_fields`` salvage what it can.

API quirks vs the other adapters:
  - no ``generate()`` / processor -- a custom ``model.infer(tokenizer, prompt,
    image_file=..., output_path=...)`` that takes an image *path* (not a PIL
    image) and writes its transcription into a directory.
  - "gundam" image config (base_size=1024, image_size=640, crop_mode=True) is
    the memory-friendly mode; "base" (image_size=1024, crop_mode=False) is
    higher fidelity but heavier. We use gundam to stay inside this 12GB card,
    the same tradeoff ``load_image_for_vram`` makes for the VLMs.

3B in bf16 is ~6GB of weights, so this runs unquantized on the 12GB GPU for
single-card images (no BitsAndBytes path like qwen3-vl needs). Needs a real
CUDA GPU. torch/transformers aren't resolved into uv.lock from here; add them
and re-run `uv lock` on the machine that'll actually run this.

Running note: can use BitsAndBytes to quantize runs, OR use
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from json_extraction import EXTRACTION_PROMPT, load_image_for_vram, parse_json_fields

from extraction.base import ExtractionResult

MODEL_ID = "baidu/Unlimited-OCR"


class UnlimitedOcrExtractor:
    name = "unlimited-ocr"

    def __init__(self) -> None:
        self._model = None
        self._tokenizer = None

    def is_available(self) -> bool:
        try:
            import torch  # noqa: F401
            import transformers  # noqa: F401
        except ImportError:
            return False
        return True

    def _load(self):
        if self._model is None:
            import torch
            from transformers import AutoModel, AutoTokenizer

            self._tokenizer = AutoTokenizer.from_pretrained(
                MODEL_ID, trust_remote_code=True
            )
            self._model = (
                AutoModel.from_pretrained(
                    MODEL_ID,
                    trust_remote_code=True,
                    use_safetensors=True,
                    torch_dtype=torch.bfloat16,
                )
                .eval()
                .cuda()
            )
        return self._model, self._tokenizer

    def extract(self, image_path: Path) -> ExtractionResult:
        model, tokenizer = self._load()

        # infer() wants a file path, so downscale to the VRAM budget and hand it
        # a temp copy rather than the 9MP original.
        with tempfile.TemporaryDirectory() as work_dir:
            resized = Path(work_dir) / "card.png"
            load_image_for_vram(image_path).save(resized)

            returned = model.infer(
                tokenizer,
                prompt=f"<image>\n{EXTRACTION_PROMPT}",
                image_file=str(resized),
                output_path=work_dir,
                base_size=1024,
                image_size=640,
                crop_mode=True,
                max_length=32768,
                no_repeat_ngram_size=35,
                ngram_window=128,
                save_results=True,
            )
            raw_output = _read_transcription(returned, Path(work_dir))

        fields = parse_json_fields(raw_output) or {}
        return ExtractionResult(fields=fields, raw_text=raw_output)


def _read_transcription(returned: object, work_dir: Path) -> str:
    """infer() writes its transcription to ``output_path`` when
    save_results=True; some builds also return it directly. Prefer the return
    value, fall back to the on-disk result file."""
    if isinstance(returned, str) and returned.strip():
        return returned
    for pattern in ("*.mmd", "*.md", "*.txt"):
        for path in sorted(work_dir.glob(pattern)):
            text = path.read_text(errors="replace").strip()
            if text:
                return text
    return ""

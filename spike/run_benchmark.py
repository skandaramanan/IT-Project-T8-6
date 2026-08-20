"""Runs one candidate extractor over the 20-card benchmark and reports accuracy.

Usage:
    uv run python spike/run_benchmark.py --model qwen2.5-vl \\
        --pdf "data/Wilfred_Prest_Survey_Data/216463/1262761_1973-0002-00052.pdf"

--pdf is only needed the first time (or after data/benchmark/images/ is
cleared) -- images are extracted once and cached, not re-pulled from the PDF
on every run, since re-parsing a 182MB/492-page PDF on every one of several
candidate-model runs would be pure waste.
"""

from __future__ import annotations

import argparse
import time
from pathlib import Path

from extract_benchmark_images import extract_benchmark_images
from ground_truth import load_ground_truth
from scoring import score_structured

from extraction.base import Extractor

EXTRACTORS: dict[str, str] = {
    # name -> "module:ClassName", imported lazily so picking one model doesn't
    # require every other candidate's dependencies to be installed
    "qwen2.5-vl": "qwen_vl_extractor:QwenVLExtractor",
    "qwen3-vl": "qwen3_vl_extractor:Qwen3VLExtractor",
    "internvl3": "internvl_extractor:InternVLExtractor",
    "molmo": "molmo_extractor:MolmoExtractor",
    "pixtral": "pixtral_extractor:PixtralExtractor",
    "nuextract3": "nuextract_extractor:NuExtractExtractor",
    "azure-doc-intel": "azure_doc_intel_extractor:AzureDocIntelExtractor",
}


def load_extractor(name: str) -> Extractor:
    if name not in EXTRACTORS:
        raise SystemExit(f"Unknown model {name!r}. Choices: {', '.join(EXTRACTORS)}")
    module_name, class_name = EXTRACTORS[name].split(":")
    import importlib

    module = importlib.import_module(module_name)
    return getattr(module, class_name)()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", required=True, choices=sorted(EXTRACTORS))
    parser.add_argument(
        "--pdf",
        type=Path,
        default=None,
        help="Source batch PDF -- only needed if data/benchmark/images/ isn't populated yet",
    )
    args = parser.parse_args()

    extractor = load_extractor(args.model)
    if not extractor.is_available():
        raise SystemExit(
            f"{args.model} is not available (missing dependency or API key)"
        )

    cards = load_ground_truth()
    missing = [card for card in cards if not card.image_path.exists()]
    if missing:
        if args.pdf is None:
            raise SystemExit(
                f"{len(missing)}/{len(cards)} benchmark images aren't cached yet -- "
                "pass --pdf to extract them (see this script's docstring)"
            )
        print(f"Extracting {len(missing)} missing benchmark images from {args.pdf}...")
        extract_benchmark_images(args.pdf)
        cards = load_ground_truth()

    print(f"Running {extractor.name} over {len(cards)} benchmark cards\n")

    scores = []
    total_time = 0.0

    for card in cards:
        start = time.monotonic()
        result = extractor.extract(card.image_path)
        elapsed = time.monotonic() - start
        total_time += elapsed

        score = score_structured(card, result.fields)
        scores.append(score)
        print(
            f"page {card.page_id}: {score.correct_fields}/{score.total_fields} fields "
            f"({score.accuracy:.0%}) in {elapsed:.1f}s"
        )

    print(f"\n--- {extractor.name} summary ---")
    print(f"Total time: {total_time:.1f}s ({total_time / len(cards):.1f}s/card avg)")

    total_correct = sum(s.correct_fields for s in scores)
    total_fields = sum(s.total_fields for s in scores)
    print(
        f"Field accuracy: {total_correct}/{total_fields} ({total_correct / total_fields:.1%})"
    )


if __name__ == "__main__":
    main()

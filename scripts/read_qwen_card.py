"""Read one coding card with the Qwen server and add its record to the results.

QWEN_SERVER_MODEL=qwen/qwen2.5-vl-7b QWEN_MAX_PIXELS=2000000 \\
    uv run python scripts/read_qwen_card.py <region> <pdf> <page>

For a card the segmenter takes for a front, once it is in
``docs/runs/it123-verified-coding.json``: the Gemini run recovers such a card by
reading the front with the coding prompt, which the Qwen run never does
(216414 p194, 216436 p271). Rerunning the folder would read it too, but
segments every page of the PDF again; this reads only the one card.

The reading is cached where ``survey extract`` caches it, so a later rerun
replays it. The record is built on its own, without the PDF's other pages, so
it is flagged ``unplaced``; the region's identities are then settled again.
"""

import argparse
import json
import tempfile
from pathlib import Path

from survey.association.records import build_dwelling_records
from survey.extraction.qwen_server import QwenServerExtractor
from survey.pipeline import (
    RunSummary,
    _check_config,
    _coding_cards,
    _reading,
    _score,
    _settle_identities,
    read_records,
    read_verified_coding,
)
from survey.records import schema_errors, write_atomic
from survey.segmentation.pdf_pages import extract_image
from survey.segmentation.segmenter import CardType, SegmentedCard

REPO = Path(__file__).resolve().parents[1]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("region")
    parser.add_argument("pdf", help="the PDF's file name, as in the results")
    parser.add_argument("page", type=int)
    args = parser.parse_args()
    region, page = args.region, args.page
    verified = read_verified_coding(
        REPO / "docs/runs/it123-verified-coding.json", region
    )
    if (args.pdf, page) not in verified:
        raise SystemExit(f"{args.pdf} p{page} is not verified coding; add it first")
    pdf = REPO / "data/Wilfred_Prest_Survey_Data" / region / args.pdf

    extractor = QwenServerExtractor()
    if not extractor.is_available():
        raise SystemExit(extractor.unavailable)
    raw_dir = REPO / "data/runs" / region
    out = REPO / "results" / extractor.name / f"{region}.jsonl"
    _check_config(raw_dir / extractor.cache_name, extractor.config)
    _check_config(out.parent, extractor.config)
    previous = read_records(out, region)
    if any((pdf.name, page) in _coding_cards(record) for record in previous):
        raise SystemExit(f"{pdf.name} p{page} already has a record")

    with tempfile.TemporaryDirectory() as tmp:
        image = Path(tmp) / "card.png"
        extract_image(pdf, page, image)
        result = _reading(image, pdf, page, extractor, raw_dir, RunSummary())
        if not (result and result.fields):
            raise SystemExit(f"{pdf.name} p{page}: no usable reading")
        card = SegmentedCard(CardType.NUMERIC_CODING, image, pdf, 0)
        (record,), _, _ = build_dwelling_records(
            [(card, result)],
            region=region,
            batch=pdf.name,
            locate=lambda _: (pdf.name, page),
            fronts_read=False,
        )
    _score(record, {(pdf.name, page): result}, extractor.model_id)
    records = sorted([*previous, record], key=lambda r: min(_coding_cards(r)))
    _settle_identities(records)
    for each in records:
        if errors := schema_errors(each):
            raise SystemExit("; ".join(errors))
    write_atomic(out, "".join(json.dumps(each) + "\n" for each in records))
    household = record["dwelling"]["households"][0]
    print(f"{pdf.name} p{page}: {household['record_id']}, {len(records)} records")


if __name__ == "__main__":
    main()

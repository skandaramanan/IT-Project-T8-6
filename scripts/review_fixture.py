"""Adapt the r01 schema example for local review against its original PDF.

The example is an illustrative excerpt, not fresh extraction or ground truth.
No model calls, source edits, GitHub uploads or invented households are needed.
"""

import argparse
import json
import runpy
from copy import deepcopy
from hashlib import sha256
from pathlib import Path

from pypdf import PdfReader

from survey.records import validate_records

REPO = Path(__file__).resolve().parents[1]
REGION = "216460"
PDF = "1260908_1973-0002-00049.pdf"
ROLES = ["survey-front", "survey-back", "coding-front", "coding-back"]


def adapt_record(example):
    record = deepcopy(example)
    record.update(region=REGION, batch=PDF)
    for card in record["dwelling"]["households"][0]["cards"]:
        card["image"] = PDF
    # The illustrative excerpt puts all four roles on its one household.
    # Verified original role/page pairs can populate IT-89's dwelling cards.
    household = record["dwelling"]["households"][0]
    record["dwelling"]["cards"] = [
        c for c in household["cards"] if c["role"] in {"survey-front", "survey-back"}
    ]
    household["cards"] = [
        c
        for c in household["cards"]
        if c["role"] not in {"survey-front", "survey-back"}
    ]

    # The schema example's scores are illustrative, not measured confidences.
    def clear_confidence(node):
        if isinstance(node, dict):
            if "confidence" in node:
                node["confidence"] = None
            for value in node.values():
                clear_confidence(value)
        elif isinstance(node, list):
            for value in node:
                clear_confidence(value)

    clear_confidence(record)
    validate_records([record], REGION)
    return record


def verify_fixture_pdf(scan_root):
    source = scan_root / REGION / PDF
    reader = PdfReader(source)
    for page, role in enumerate(ROLES, 1):
        fixture = (REPO / "tests/fixtures" / f"r01-{role}.jpg").read_bytes()
        images = reader.pages[page - 1]["/Resources"]["/XObject"].get_object()
        # These fixtures were copied from the original JPEG streams. Comparing
        # decoded/re-encoded images would lose that byte-for-byte check.
        hashes = {
            sha256(obj._data).digest()
            for ref in images.values()
            if (obj := ref.get_object()).get("/Subtype") == "/Image"
        }
        if sha256(fixture).digest() not in hashes:
            raise ValueError(f"Original PDF page {page} does not match r01-{role}.jpg")


def prepare_fixture(root, scan_root):
    root, scan_root = root.resolve(), scan_root.resolve()
    if root.is_relative_to(REPO) or root.is_relative_to(scan_root):
        raise ValueError("Choose a test directory outside the code checkout and scans")
    if root.exists() and any(root.iterdir()):
        raise ValueError("Choose a new empty test directory")
    verify_fixture_pdf(scan_root)
    example = json.loads((REPO / "schema/example-r01-excerpt.json").read_text())
    record = adapt_record(example)
    root.mkdir(parents=True, exist_ok=True)
    source = root / f"{REGION}.jsonl"
    source.write_text(json.dumps(record, ensure_ascii=False) + "\n", encoding="utf-8")
    (root / "README.txt").write_text(
        "Local r01 fixture review test; not a production extracted dataset.\n"
        "Record values/annotations come from schema/example-r01-excerpt.json.\n"
        "Confidence scores are unknown because the example scores are illustrative.\n"
        "Original PDF pages 1-4 were verified against the fixture JPEG bytes.\n"
        "This is one dwelling/one household; it does not test multiple households.\n"
        "Review edits and uploads target copies and a local remote.git only.\n",
        encoding="utf-8",
    )
    print(
        "Fixture-based sample: illustrative values, real original scans, unknown confidence."
    )
    prepare_sample = runpy.run_path(str(REPO / "scripts/review_sample.py"))[
        "prepare_sample"
    ]
    return prepare_sample(
        source,
        scan_root,
        root / "review",
        ["Weekly Rent", "Age of Head", "Sex of Head"],
        limit=1,
        port=8876,
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "directory", type=Path, help="new empty directory outside the repository"
    )
    parser.add_argument("--scan-root", type=Path, required=True)
    args = parser.parse_args()
    try:
        prepare_fixture(args.directory, args.scan_root)
    except (ValueError, OSError) as error:
        parser.error(str(error))

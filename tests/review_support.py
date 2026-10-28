"""Explicitly synthetic review dataset. No model calls or real transcriptions."""

import json
import subprocess
import sys
from copy import deepcopy
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from survey.extraction.record import build_record
from survey.records import RecordStore, Reference
from survey.review.api import Settings
from survey.review.relinking import finish_records
from survey.review.scans import LocalScanSource
from survey.review.service import ReviewService


def card_record():
    """The synthetic dwelling as extraction builds it: per-card, unfinished."""
    fields = {
        "Municipality": "27",
        "Number of Dwelling": "6",
        "Number of Household": "1",
        "Weekly Rent": "04",
        "Occupation of H.": "4",
        "Age of Head": "50",
        "Garden": "1",
    }
    first = build_record(
        fields, region="demo", image="synthetic.pdf", page=1, batch="synthetic.pdf"
    )
    second = build_record(
        {**fields, "Number of Household": "2", "Weekly Rent": "12"},
        region="demo",
        image="synthetic.pdf",
        page=2,
        batch="synthetic.pdf",
    )
    first["dwelling"]["households"].append(second["dwelling"]["households"][0])
    field = {
        "value": "Synthetic address only",
        "status": "ok",
        "confidence": None,
        "source": "survey-front",
    }
    first["dwelling"]["address"] = deepcopy(field)
    first["dwelling"]["handwritten"] = {"notes": deepcopy(field)}
    first["dwelling"]["households"][1]["persons"] = [
        {"relationship": {"value": "Head", "status": "ok", "confidence": None}}
    ]
    first["dwelling"]["cards"] = [
        {"role": "survey-front", "image": "synthetic.pdf", "page": 3},
        {"role": "survey-back", "image": "synthetic.pdf", "page": 4},
    ]
    first["dwelling"]["notes"] = [
        {
            "text": {
                "value": "Synthetic reverse notes",
                "status": "ok",
                "confidence": None,
                "source": "survey-back",
            },
            "page": 4,
            "front_page": 3,
            "household_id": None,
        }
    ]
    return first


def legacy(record):
    """Convert a per-card record to published 0.6.0 (shared first-card fields)."""
    record = deepcopy(record)
    d, hs = record["dwelling"], record["dwelling"]["households"]
    shared = {
        "municipality": deepcopy(hs[0]["municipality"]),
        "dwelling_no": hs[0].pop("dwelling_no"),
        "house": hs[0].pop("house"),
    }
    for h in hs[1:]:
        h.pop("dwelling_no")
        h.pop("house")
    record["dwelling"] = {**shared, **d}
    record["schema_version"] = "0.6.0"
    return record


def synthetic_record():
    """The synthetic dwelling in the active shape."""
    return prepare_shape(card_record())


# Module-level switch flipped by the `shape` fixture: False = published 0.6.0
# (shared first-card ownership), True = prepared 0.7.0 (per-card ownership).
PREPARED = False


@pytest.fixture(params=["0.6.0", "0.7.0"])
def shape(request, monkeypatch):
    monkeypatch.setattr(sys.modules[__name__], "PREPARED", request.param == "0.7.0")
    return request.param


def per_card(pointer, index=0):
    """Map a legacy shared-building pointer to its 0.7.0 per-card pointer."""
    if not PREPARED:
        return pointer
    for tail in ("municipality", "dwelling_no"):
        if pointer == f"/dwelling/{tail}":
            return f"/dwelling/households/{index}/{tail}"
    if pointer.startswith("/dwelling/house/"):
        return f"/dwelling/households/{index}/house/{pointer.rsplit('/', 1)[1]}"
    return pointer


def prepare_shape(record):
    """Return a per-card (build_record) record in the active data shape."""
    return finish_records([record])[0] if PREPARED else legacy(record)


def refs():
    return [
        Reference(
            "demo", "synthetic.pdf", 1, "/dwelling/households/0/coding/weekly_rent"
        ),
        Reference(
            "demo", "synthetic.pdf", 2, "/dwelling/households/1/coding/weekly_rent"
        ),
        Reference("demo", "synthetic.pdf", 1, per_card("/dwelling/house/garden")),
        Reference("demo", "synthetic.pdf", 1, per_card("/dwelling/municipality")),
        Reference(
            "demo", "synthetic.pdf", 1, "/dwelling/households/0/head/occupation_of_head"
        ),
    ]


def git(path, *args):
    return subprocess.run(
        ["git", "-C", str(path), *args], check=True, capture_output=True, text=True
    ).stdout.strip()


def write_record(path, record):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record, ensure_ascii=False) + "\n", encoding="utf-8")


def synthetic_pdf(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    images = []
    for page, color in [(1, "white"), (2, "#f0e2b8"), (3, "white"), (4, "white")]:
        image = Image.new("RGB", (1000, 650), color)
        draw = ImageDraw.Draw(image)
        draw.text(
            (50, 40),
            f"SYNTHETIC TEST CARD - NOT A TRANSCRIPTION - PAGE {page}",
            fill="black",
            font_size=24,
        )
        draw.text(
            (50, 100),
            f"Household {page} / Rent: {'04' if page == 1 else '12'}",
            fill="black",
            font_size=24,
        )
        images.append(image)
    images[0].save(path, save_all=True, append_images=images[1:])


def setup_review(root: Path, with_git=False):
    checkout = root / "data checkout"
    results = checkout / "results"
    write_record(results / "demo.jsonl", synthetic_record())
    scans = root / "scans"
    synthetic_pdf(scans / "demo" / "synthetic.pdf")
    flags = root / "flags.jsonl"
    flags.write_text(
        "".join(
            json.dumps(
                {
                    "region": r.region,
                    "pdf": r.pdf,
                    "page": r.page,
                    "field_path": r.field_path,
                }
            )
            + "\n"
            for r in refs()
        )
    )
    if with_git:
        remote = root / "remote.git"
        git(root, "init", "--bare", str(remote))
        git(checkout, "init", "-b", "review-data")
        git(checkout, "config", "user.name", "Synthetic test")
        git(checkout, "config", "user.email", "synthetic@example.invalid")
        git(checkout, "add", "results/demo.jsonl")
        git(checkout, "commit", "-m", "Seed synthetic dataset")
        git(checkout, "remote", "add", "origin", str(remote))
        git(checkout, "push", "-u", "origin", "review-data")
    store = RecordStore(results)
    scan_source = LocalScanSource(scans, root / "cache")
    service = ReviewService(store, refs(), [], scan_source)
    settings = Settings(scans, checkout, flags, root / "cache", sync_interval=3600)
    return service, settings


def decide(
    service, ref=None, action="correct", value="09", request_id="first", version=None
):
    ref = ref or refs()[1]
    return service.apply_decision(
        ref.item_id,
        action,
        "Test Reviewer",
        version or service.item(ref.item_id)["version"],
        request_id,
        value if action == "correct" else None,
    )

"""Read only the inspected replacement-scan additions; build offline by default.

Run in the dedicated skandar/it-123-216436-gemini-additions worktree. Workers 0 and 1
use separate existing API keys; every response is cached before proceeding.
No normal pipeline discovery or previous-region rereads occur.
"""

import argparse
import hashlib
import json
import os
import subprocess
import time
from collections import Counter
from copy import deepcopy
from dataclasses import asdict, replace
from pathlib import Path

from survey.association.notes import ReverseSlot, attach_notes, read_notes
from survey.association.records import build_dwelling_records
from survey.extraction.base import ExtractionResult
from survey.extraction.card_fields import FIELD_SCHEMA_BY_NAME
from survey.extraction.gemini import GeminiExtractor
from survey.extraction.record import (
    FIELD_MAP,
    clean_text,
    fill_identity,
    identity_of,
    normalise,
)
from survey.pipeline import (
    _coding_cards,
    _corrected_fields,
    _merge,
    _score,
    read_records,
)
from survey.records import schema_errors, validate_records, write_atomic
from survey.segmentation.pdf_pages import extract_image
from survey.segmentation.segmenter import CardType, SegmentedCard

ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / "data/216436-additions"
PDF_NAME = "1264179_1973-0002-00025.pdf"
PDF = ROOT / "data/Wilfred_Prest_Survey_Data/216436" / PDF_NAME
MODEL = "gemini-3.5-flash-lite"
CODING = (
    517,
    521,
    525,
    531,
    535,
    539,
    543,
    547,
    551,
    555,
    559,
    563,
    567,
    573,
    577,
    581,
    585,
    589,
    593,
)
FRONTS = (
    515,
    519,
    523,
    527,
    529,
    533,
    537,
    541,
    545,
    549,
    553,
    557,
    561,
    565,
    571,
    575,
    579,
    583,
    587,
    591,
)
READERS = {
    "coding": {},
    "front": {"survey_front": True},
    "notes": {"reverse_notes": True},
}


def isolated():
    """Fail closed before creating clients or writing outputs."""
    assert Path.cwd().resolve() == ROOT
    branch = subprocess.check_output(
        ["git", "branch", "--show-current"], cwd=ROOT, text=True
    ).strip()
    if branch != "skandar/it-123-216436-gemini-additions":
        raise RuntimeError("not the isolated additions branch")
    for name in (
        "data",
        "data/Wilfred_Prest_Survey_Data",
        "results",
        "backend",
        ".venv",
    ):
        path = ROOT / name
        if path.is_symlink() or ROOT not in path.resolve().parents:
            raise RuntimeError(f"shared path: {path}")
    import survey

    if ROOT not in Path(survey.__file__).resolve().parents:
        raise RuntimeError("imported another checkout")
    if (ROOT / "backend/survey/merge_runs.py").exists():
        raise RuntimeError("IT-125 implementation found in this checkout")


def cache(kind, page):
    suffix = {
        "coding": "",
        "front": "-survey-front",
        "notes": "-reverse-notes",
        "identity": "-identity",
    }[kind]
    return ROOT / "data/runs/216436" / (MODEL + suffix) / f"{PDF.stem}_p{page:04d}.json"


def jobs():
    return (
        [("coding", p) for p in CODING]
        + [("front", p) for p in FRONTS]
        + [("notes", p + 1) for p in FRONTS]
    )


def read_cache(kind, page):
    result = ExtractionResult(**json.loads(cache(kind, page).read_text()))
    if not result.fields:
        raise RuntimeError(f"empty reading: {kind} p{page}")
    return result


def extract(worker, credentials):
    isolated()
    values = {}
    for line in credentials.read_text().splitlines():
        key, sep, value = line.partition("=")
        if sep:
            values[key.strip()] = value.strip().strip("\"'")
    key = values.get(f"GEMINI_API_KEY_{worker + 1}") or values.get("GEMINI_API_KEY")
    if not key:
        raise RuntimeError("no configured Gemini credential for this worker")
    os.environ["GEMINI_API_KEY"] = key
    os.environ["GEMINI_MODEL"] = MODEL
    for setting in (
        "GEMINI_MEDIA_RESOLUTION",
        "GEMINI_CONFIDENCE_BAND",
        "GEMINI_STRUCK_DETECTION",
    ):
        os.environ.pop(setting, None)
    readers = {kind: GeminiExtractor(**kwargs) for kind, kwargs in READERS.items()}
    for index, (kind, page) in enumerate(jobs()):
        if index % 2 != worker:
            continue
        if cache(kind, page).exists():
            read_cache(kind, page)
            print(f"cached {kind} p{page}", flush=True)
            continue
        image = RUN / "images" / f"p{page:04d}.png"
        image.parent.mkdir(parents=True, exist_ok=True)
        extract_image(PDF, page, image)
        started = time.monotonic()
        try:
            result = readers[kind].extract(image)
            if not result.fields:
                raise RuntimeError("no fields returned")
            # The generic parser can repair incomplete objects. A handoff must
            # retain a complete JSON object, rather than a silent partial read.
            raw = result.raw_text or ""
            json.loads(raw[raw.index("{") : raw.rindex("}") + 1])
            destination = cache(kind, page)
            destination.parent.mkdir(parents=True, exist_ok=True)
            write_atomic(destination, json.dumps(asdict(result)) + "\n")
            print(f"read {kind} p{page}: {len(result.fields)} fields", flush=True)
        except Exception as error:  # noqa: BLE001 -- redact API credentials at boundary
            message = str(error).replace(key, "[redacted]")[:400]
            print(f"FAILED {kind} p{page}: {message}", flush=True)
            raise RuntimeError(f"{kind} p{page} failed; resume from cache") from None
        time.sleep(max(0, 7 - (time.monotonic() - started)))


def extract_identity(credentials):
    """Only malformed identities get the existing independent crop prompt."""
    isolated()
    values = {}
    for line in credentials.read_text().splitlines():
        key, sep, value = line.partition("=")
        if sep:
            values[key.strip()] = value.strip().strip("\"'")
    key = values.get("GEMINI_API_KEY_3") or values.get("GEMINI_API_KEY")
    if not key:
        raise RuntimeError("no credential for identity reread")
    os.environ["GEMINI_API_KEY"] = key
    os.environ["GEMINI_MODEL"] = MODEL
    for setting in (
        "GEMINI_MEDIA_RESOLUTION",
        "GEMINI_CONFIDENCE_BAND",
        "GEMINI_STRUCK_DETECTION",
    ):
        os.environ.pop(setting, None)
    reader = GeminiExtractor(identity=True)
    for page in CODING:
        try:
            identity_of(read_cache("coding", page).fields)
            continue
        except ValueError:
            pass
        destination = cache("identity", page)
        if destination.exists():
            read_cache("identity", page)
            continue
        try:
            result = reader.extract(RUN / "images" / f"p{page:04d}.png")
        except Exception as error:  # noqa: BLE001 -- redact credential at boundary
            raise RuntimeError(str(error).replace(key, "[redacted]")[:400]) from None
        if not result.fields:
            raise RuntimeError(f"identity p{page}: no fields")
        destination.parent.mkdir(parents=True, exist_ok=True)
        write_atomic(destination, json.dumps(asdict(result)) + "\n")
        print(f"read identity p{page}", flush=True)


def correction_index(manifest):
    """Only inspected pages/fields may be corrected, without duplicate decisions."""
    decisions = {}
    for item in manifest["corrections"]:
        kind, page, field = item["kind"], item["page"], item["field"]
        allowed = (
            kind == "front"
            and page in FRONTS
            and field == "Dwelling Number (top-left corner)"
        ) or (kind == "coding" and page in CODING and field in FIELD_MAP)
        key = kind, page, field
        if not allowed or key in decisions:
            raise ValueError(f"invalid or repeated correction: {key}")
        decisions[key] = item
    return decisions


def corrected_reading(kind, page, result, decisions):
    """Apply inspected changes to a copy; refuse an unexpected machine reading."""
    fields = dict(result.fields)
    for (target_kind, target_page, label), item in decisions.items():
        if (target_kind, target_page) != (kind, page):
            continue
        if fields.get(label) != item["original_value"]:
            raise ValueError(
                f"{kind} p{page} {label}: machine reading changed; recheck the scan"
            )
        fields[label] = item["value"]
    return replace(result, fields=fields)


def annotate_corrections(record, originals, decisions):
    """NFR-05: keep the machine value on the field selected for this record."""
    dwelling = record["dwelling"]

    def mark(field, kind, page, label):
        if (kind, page, label) not in decisions:
            return
        raw = originals[kind, page].fields.get(label)
        clean = clean_text if kind == "front" else normalise
        field.update(origin="corrected", original_value=clean(raw) or None)

    for index, household in enumerate(dwelling["households"]):
        page = household["cards"][0]["page"]
        groups = {
            "household": household,
            "head": household["head"],
            "counts": household["counts"],
            "coding": household["coding"],
        }
        if index == 0:
            groups.update(dwelling=dwelling, house=dwelling["house"])
        for label, (key, group) in FIELD_MAP.items():
            if group in groups:
                mark(groups[group][key], "coding", page, label)
        mark(household["municipality"], "coding", page, "Municipality")
    # Dwelling number is the only corrected front label. It is present on
    # every inspected front, so the first front supplies the selected value.
    fronts = [
        card for card in dwelling.get("cards", []) if card["role"] == "survey-front"
    ]
    if fronts:
        mark(
            dwelling["handwritten"]["dwelling_no"],
            "front",
            fronts[0]["page"],
            "Dwelling Number (top-left corner)",
        )


def protect_published_corrections(published, rebuilt):
    """Refuse to replace a reviewed/corrected payload with a different one."""
    targets = {_coding_cards(record): record for record in rebuilt}
    for record in published:
        for path, field in _corrected_fields(record):
            target = targets.get(_coding_cards(record))
            try:
                for key in path:
                    target = target[key]
            except (KeyError, IndexError, TypeError):
                target = None
            if target != field:
                raise ValueError(
                    "rebuild would overwrite a published correction or review"
                )


def build():
    isolated()
    # Read the original committed Gemini baseline, never the IT-125 working file.
    original = subprocess.check_output(
        [
            "git",
            "show",
            "556913316ae04aeaca0b5332198975bc176d7bc1:results/216436.jsonl",
        ],
        cwd=ROOT,
        text=True,
    )
    previous = [json.loads(line) for line in original.splitlines() if line.strip()]
    manifest = json.loads(
        (ROOT / "docs/runs/216436-source-corrections.json").read_text()
    )
    if (
        manifest["pdf"] != PDF_NAME
        or manifest["region"] != "216436"
        or manifest["pdf_sha256"] != hashlib.sha256(PDF.read_bytes()).hexdigest()
    ):
        raise ValueError("source corrections belong to a different scan")
    decisions = correction_index(manifest)
    originals = {}
    cards, readings, reread = [], {}, set()
    for kind, page in jobs():
        if kind == "notes":
            continue
        card = SegmentedCard(
            CardType.FRONT if kind == "front" else CardType.NUMERIC_CODING,
            RUN / "images" / f"p{page:04d}.png",
            PDF,
            page - 1,
        )
        cards.append(card)
        original_result = read_cache(kind, page)
        originals[kind, page] = original_result
        result = corrected_reading(kind, page, original_result, decisions)
        try:
            identity_of(result.fields)
            valid_identity = True
        except ValueError:
            valid_identity = False
        if kind == "coding" and not valid_identity and cache("identity", page).exists():
            try:
                fields = fill_identity(
                    result.fields, read_cache("identity", page).fields
                )
            except ValueError:
                pass  # ambiguity stays visible as a null identity and review flag
            else:
                result = replace(result, fields=fields)
                reread.add(card)
        readings[card] = result
    cards.sort(key=lambda card: card.page_index)

    def locate(card):
        return PDF_NAME, card.page_index + 1

    added, _, unplaced = build_dwelling_records(
        [(card, readings[card]) for card in cards],
        region="216436",
        batch=PDF_NAME,
        locate=locate,
        reread=reread,
    )
    # All 20 visually verified fronts have their own following back. Do not
    # fabricate an association for a front the existing rules cannot place.
    slots = [
        ReverseSlot(
            card,
            RUN / "images" / f"p{card.page_index + 2:04d}.png",
            card.page_index + 2,
        )
        for card in cards
        if card.card_type is CardType.FRONT
    ]
    notes = read_notes(slots, lambda slot: read_cache("notes", slot.page))
    unattached = attach_notes(added, notes, locate)
    by_place = {locate(card): result for card, result in readings.items()}
    for record in added:
        _score(record, by_place, MODEL)
        annotate_corrections(record, originals, decisions)
    merged = _merge(deepcopy(previous), added)
    before = {_coding_cards(record): record for record in previous}
    after = {_coding_cards(record): record for record in merged}
    changed = [
        sorted(key) for key, record in before.items() if after.get(key) != record
    ]
    if changed:
        raise RuntimeError(f"existing baseline changed: {changed}")
    new_sources = {source for record in merged for source in _coding_cards(record)}
    old_sources = {source for record in previous for source in _coding_cards(record)}
    expected = {(PDF_NAME, page) for page in CODING}
    if new_sources - old_sources != expected or old_sources - new_sources:
        raise RuntimeError("coding inventory differs from the inspected additions")
    actual_links = {
        (front["page"], coding["page"])
        for record in added
        for front in record["dwelling"].get("cards", [])
        if front["role"] == "survey-front"
        for household in record["dwelling"]["households"]
        for coding in household["cards"]
        if coding["role"] == "coding-front"
    }
    expected_links = {
        (pair["front_page"], pair["coding_page"])
        for pair in manifest["verified_associations"]
    }
    if actual_links != expected_links or unattached:
        raise ValueError("rebuilt associations differ from the scan-verified inventory")
    validate_records(merged, "216436")
    for record in merged:
        if errors := schema_errors(record):
            raise RuntimeError(str(errors))
    cost = sum(read_cache(kind, page).cost_usd or 0 for kind, page in jobs())
    identity_pages = [page for page in CODING if cache("identity", page).exists()]
    cost += sum(read_cache("identity", page).cost_usd or 0 for page in identity_pages)
    report = {
        "model": MODEL,
        "banded": False,
        "struck_detection": False,
        "media_resolution": "default",
        "original_records": len(previous),
        "records": len(merged),
        "coding_sources_before": len(old_sources),
        "coding_sources_after": len(new_sources),
        "new_coding_pages": list(CODING),
        "fronts_read": len(FRONTS),
        "source_corrections": len(decisions),
        "corrections_manifest": "docs/runs/216436-source-corrections.json",
        "verified_associations": sorted([list(pair) for pair in actual_links]),
        "identity_reread_pages": sorted(card.page_index + 1 for card in reread),
        "identity_crop_pages": identity_pages,
        "null_record_id_pages": [
            card["page"]
            for record in added
            for household in record["dwelling"]["households"]
            if household["record_id"] is None
            for card in household["cards"]
            if card["role"] == "coding-front"
        ],
        "front_pages": list(FRONTS),
        "notes_read": len(slots),
        "unattached_front_pages": [
            note.slot.front.page_index + 1 for note in unattached
        ],
        "unplaced_card_pages": [card.page_index + 1 for card in unplaced],
        "existing_records_changed": 0,
        "new_record_flags": dict(
            Counter(
                flag for record in added for flag in record["dwelling"].get("flags", [])
            )
        ),
        "new_unplaced_coding_pages": [
            card["page"]
            for record in added
            if "unplaced" in record["dwelling"].get("flags", [])
            for household in record["dwelling"]["households"]
            for card in household["cards"]
            if card["role"] == "coding-front"
        ],
        "omitted_coding_fields": [
            {"page": page, "field": field}
            for page in CODING
            for field in sorted(
                set(FIELD_SCHEMA_BY_NAME)
                - corrected_reading(
                    "coding", page, originals["coding", page], decisions
                ).fields.keys()
            )
        ],
        "estimated_usage_cost_usd": cost,
        "excluded_blank_crossed_out_page": 570,
        "pdf_sha256": hashlib.sha256(PDF.read_bytes()).hexdigest(),
        "source_download_name": "1973-0002-00025-00001.pdf",
        "canonical_pdf_name": PDF_NAME,
    }
    protect_published_corrections(
        read_records(ROOT / "results/216436.jsonl", "216436"), merged
    )
    output = "".join(json.dumps(record) + "\n" for record in merged)
    write_atomic(ROOT / "results/216436.jsonl", output)
    write_atomic(RUN / "additions.jsonl", "".join(json.dumps(r) + "\n" for r in added))
    unattached_pages = {note.slot.front.page_index + 1 for note in unattached}
    write_atomic(
        RUN / "unattached-fronts.json",
        json.dumps(
            [
                {"page": page, "fields": read_cache("front", page).fields}
                for page in FRONTS
                if page in unattached_pages
            ],
            indent=2,
        )
        + "\n",
    )
    write_atomic(
        RUN / "unattached-notes.json",
        json.dumps(
            [
                {
                    "front_page": note.slot.front.page_index + 1,
                    "back_page": note.slot.page,
                    "text": note.text,
                }
                for note in unattached
            ],
            indent=2,
        )
        + "\n",
    )
    write_atomic(
        ROOT / "docs/runs/216436-gemini-additions.json",
        json.dumps(report, indent=2) + "\n",
    )
    print(json.dumps(report, indent=2), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--worker", type=int, choices=(0, 1))
    parser.add_argument("--credentials", type=Path)
    parser.add_argument("--identity", action="store_true")
    args = parser.parse_args()
    if args.identity:
        if args.credentials is None:
            parser.error("--credentials is required for identity extraction")
        extract_identity(args.credentials)
    elif args.worker is None:
        build()
    else:
        if args.credentials is None:
            parser.error("--credentials is required for extraction")
        extract(args.worker, args.credentials)

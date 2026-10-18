"""FR-17: a fixture batch runs end to end (AC1) and an unrecognised page is
skipped while the rest are processed (AC2).

The batch PDF is built in tmp_path from tests/fixtures/, and the extractor is a
fake, so nothing here touches data/ or calls Gemini.
"""

import json
import logging
from pathlib import Path
from typing import ClassVar

import jsonschema
import numpy as np
import pytest
from PIL import Image

from survey import pipeline
from survey.association import records as association
from survey.extraction.base import ExtractionResult
from survey.extraction.record import build_omitted_field, build_record
from survey.pipeline import MAX_FAILURE_STREAK, MergeRefused, _merge, run

FIXTURES = Path(__file__).parent / "fixtures"
SCHEMA = json.loads(
    (Path(__file__).parent.parent / "schema/record-envelope.schema.json").read_text()
)
ROLES = ["survey-front", "survey-back", "coding-front", "coding-back"]


class FakeExtractor:
    """Reads every coding card as municipality 27, dwelling 6, next household."""

    name = model_id = "gemini-3.5-flash-lite"
    # A survey front (page 1 or 5 of a two-record batch) read with the coding
    # prompt spells no record_id, as on the real cards.
    reads_fronts = False

    def __init__(self, fail_on: int | None = None) -> None:
        self.calls = 0
        self.fail_on = fail_on

    def is_available(self) -> bool:
        return True

    def extract(self, image_path: Path) -> ExtractionResult:
        if not self.reads_fronts and image_path.name in ("p0001.png", "p0005.png"):
            return ExtractionResult(raw_text="{}")
        self.calls += 1
        if self.calls == self.fail_on:
            raise RuntimeError("503 from the API")
        fields = {
            "Municipality": "27",
            "Number of Dwelling": "6",
            "Number of Household": str(self.calls),
            "Garden": "1",
        }
        raw = {**fields, "Garden": {"value": "1", "confidence": "high"}}
        return ExtractionResult(fields=fields, raw_text=json.dumps(raw))


class FrontExtractor(FakeExtractor):
    """Reads every survey front as dwelling 6, so r01 and r02 share it."""

    name = "gemini-3.5-flash-lite-survey-front"

    def extract(self, image_path: Path) -> ExtractionResult:
        self.calls += 1
        fields = {"Dwelling Number (top-left corner)": "6", "Address": "6 Hall St."}
        return ExtractionResult(fields=fields, raw_text=json.dumps(fields))


class KilledExtractor(FakeExtractor):
    def extract(self, image_path: Path) -> ExtractionResult:
        if self.calls == 1:
            raise KeyboardInterrupt
        return super().extract(image_path)


class UnreadableOnceExtractor(FakeExtractor):
    def extract(self, image_path: Path) -> ExtractionResult:
        result = super().extract(image_path)
        if self.calls == 1:
            return ExtractionResult(raw_text="not json")
        return result


class GarbageExtractor(FakeExtractor):
    def extract(self, image_path: Path) -> ExtractionResult:
        self.calls += 1
        return ExtractionResult(raw_text="not json")


class FlakyExtractor(FakeExtractor):
    def extract(self, image_path: Path) -> ExtractionResult:
        if self.calls + 1 == 3:
            return super().extract(image_path)
        self.calls += 1
        raise RuntimeError("503 from the API")


class DownExtractor(FakeExtractor):
    def extract(self, image_path: Path) -> ExtractionResult:
        self.calls += 1
        raise RuntimeError("429 RESOURCE_EXHAUSTED")


def _batch(tmp_path: Path, pages: list[Path], unit: str = "unit") -> Path:
    scan_dir = tmp_path / "scans" / unit
    scan_dir.mkdir(parents=True)
    images = []
    for page in pages:
        image = Image.open(page).convert("RGB")
        # The segmenter works at 900px anyway; full-size scans only make the
        # pipeline's lossless page write slow.
        image.thumbnail((1200, 1200))
        images.append(image)
    images[0].save(scan_dir / f"{unit}.pdf", save_all=True, append_images=images[1:])
    return scan_dir


def _fixture_pages(*records: str) -> list[Path]:
    return [FIXTURES / f"{record}-{role}.jpg" for record in records for role in ROLES]


def _stray_page(tmp_path: Path) -> Path:
    """Faintly inked (bleed-through) and unruled, landing third in a
    reverse/coding run (FR-21): too faint to be another coding card."""
    rng = np.random.default_rng(0)
    pixels = np.where(rng.random((500, 800)) < 0.01, 0, 255).astype("uint8")
    path = tmp_path / "stray.jpg"
    Image.fromarray(pixels, mode="L").save(path)
    return path


def _read(out_dir: Path, region: str = "north") -> list[dict]:
    path = out_dir / f"{region}.jsonl"
    return [json.loads(line) for line in path.open()] if path.exists() else []


def test_a_fixture_batch_runs_end_to_end_and_writes_valid_json(tmp_path):
    scan_dir = _batch(tmp_path, _fixture_pages("r01", "r02"))
    out_dir, raw_dir = tmp_path / "out", tmp_path / "raw"

    summary = run(
        scan_dir,
        region="north",
        extractor=FakeExtractor(),
        out_dir=out_dir,
        raw_dir=raw_dir,
    )

    records = _read(out_dir)
    assert summary.records == len(records) == 2
    assert summary.skipped_pages == summary.failed_cards == 0
    assert summary.unplaced_cards == 0  # fronts not read; scan order groups
    for record in records:
        jsonschema.validate(record, SCHEMA)
        card = record["dwelling"]["households"][0]["cards"][0]
        assert card["image"] == "unit.pdf"
        assert isinstance(card["confidence"], float)
    household = records[0]["dwelling"]["households"][0]
    assert household["record_id"] == "27-0006-01"
    assert [
        c["page"] for r in records for c in r["dwelling"]["households"][0]["cards"]
    ] == [3, 7]
    # D016: banded high is 0.92, unbanded flash-lite 0.91, a field never returned 0.0
    assert records[0]["dwelling"]["house"]["garden"]["confidence"] == 0.92
    assert records[0]["dwelling"]["municipality"]["confidence"] == 0.91
    assert records[0]["dwelling"]["house"]["bathroom"]["confidence"] == 0.0
    cache = raw_dir / "gemini-3.5-flash-lite"
    assert sorted(p.name for p in cache.iterdir()) == [
        "unit_p0003.json",
        "unit_p0007.json",
    ]


def test_an_unrecognised_page_is_skipped_and_the_rest_processed(tmp_path, caplog):
    pages = _fixture_pages("r01", "r02")
    pages.insert(3, _stray_page(tmp_path))  # after r01's coding card
    scan_dir = _batch(tmp_path, pages)

    with caplog.at_level(logging.WARNING):
        summary = run(
            scan_dir, region="north", extractor=FakeExtractor(), out_dir=tmp_path
        )

    assert summary.skipped_pages == 1
    assert summary.records == 2
    assert "unit.pdf p4: unrecognised page, skipped" in caplog.text


def test_a_failed_card_is_counted_and_the_rest_still_written(tmp_path):
    scan_dir = _batch(tmp_path, _fixture_pages("r01", "r02"))

    summary = run(
        scan_dir, region="north", extractor=FakeExtractor(fail_on=1), out_dir=tmp_path
    )

    assert summary.failed_cards == 1
    assert len(_read(tmp_path)) == 1


def test_a_damaged_pdf_is_skipped_and_the_rest_still_written(tmp_path):
    scan_dir = _batch(tmp_path, _fixture_pages("r01"))
    (scan_dir / "damaged.pdf").write_bytes(b"not a pdf")

    summary = run(scan_dir, region="north", extractor=FakeExtractor(), out_dir=tmp_path)

    assert summary.failed_pdfs == 1
    assert len(_read(tmp_path)) == 1


def test_an_undecodable_page_is_skipped_not_its_whole_pdf(tmp_path, monkeypatch):
    scan_dir = _batch(tmp_path, _fixture_pages("r01", "r02"))
    real = pipeline.extract_image

    def extract_image(pdf, number, out_path):
        if number == 2:
            raise RuntimeError("jbig2dec binary is not available")
        real(pdf, number, out_path)

    monkeypatch.setattr(pipeline, "extract_image", extract_image)
    summary = run(scan_dir, region="north", extractor=FakeExtractor(), out_dir=tmp_path)

    assert summary.failed_pdfs == 0
    assert summary.skipped_pages == 1
    assert summary.records == 2


class NoHouseholdExtractor(FakeExtractor):
    def extract(self, image_path: Path) -> ExtractionResult:
        result = super().extract(image_path)
        if self.calls == 1:
            del result.fields["Number of Household"]
        return result


def test_a_card_with_no_readable_identity_is_written_flagged(tmp_path, caplog):
    scan_dir = _batch(tmp_path, _fixture_pages("r01", "r02"))

    with caplog.at_level(logging.WARNING):
        summary = run(
            scan_dir,
            region="north",
            extractor=NoHouseholdExtractor(),
            out_dir=tmp_path,
        )

    assert summary.unreadable_cards == 1
    first, second = _read(tmp_path)
    assert first["dwelling"]["households"][0]["record_id"] is None
    assert "missing_record_id" in first["dwelling"]["flags"]
    assert second["dwelling"]["households"][0]["record_id"] == "27-0006-02"
    assert "unit.pdf p3: no record_id from 27-6-?" in caplog.text


class IdentityExtractor(FakeExtractor):
    """Reads a card's identity block as 27-6-1."""

    name = "gemini-3.5-flash-lite-identity"

    def extract(self, image_path: Path) -> ExtractionResult:
        self.calls += 1
        fields = {
            "Municipality": "27",
            "Number of Dwelling": "6",
            "Number of Household": "1",
        }
        return ExtractionResult(fields=fields, raw_text=json.dumps(fields))


def test_a_second_reading_fills_a_blank_identity_part_flagged(tmp_path):
    scan_dir = _batch(tmp_path, _fixture_pages("r01", "r02"))
    identity = IdentityExtractor()

    run(
        scan_dir,
        region="north",
        extractor=NoHouseholdExtractor(),
        out_dir=tmp_path,
        identity_extractor=identity,
    )

    first, second = _read(tmp_path)
    assert identity.calls == 1  # only the card with no record_id
    assert first["dwelling"]["households"][0]["record_id"] == "27-0006-01"
    assert "identity_reread" in first["dwelling"]["flags"]
    assert "missing_record_id" not in first["dwelling"]["flags"]
    assert second["dwelling"]["households"][0]["record_id"] == "27-0006-02"
    assert "identity_reread" not in second["dwelling"]["flags"]


class EmptySecondFrontExtractor(FrontExtractor):
    """Reads r02's "front" as nothing: it is a coding card taken for one."""

    def extract(self, image_path: Path) -> ExtractionResult:
        result = super().extract(image_path)
        return ExtractionResult(raw_text="{}") if self.calls == 2 else result


class CardOnFrontExtractor(FakeExtractor):
    reads_fronts = True


def test_a_coding_card_taken_for_a_front_is_read_as_one(tmp_path, caplog):
    scan_dir = _batch(tmp_path, _fixture_pages("r01", "r02"))

    with caplog.at_level(logging.WARNING):
        run(
            scan_dir,
            region="north",
            extractor=CardOnFrontExtractor(),
            front_extractor=EmptySecondFrontExtractor(),
            out_dir=tmp_path,
        )

    assert "unit.pdf p5: a coding card, not a front" in caplog.text
    pages = [
        card["page"]
        for record in _read(tmp_path)
        for household in record["dwelling"]["households"]
        for card in household["cards"]
    ]
    assert 5 in pages


class SameHouseholdExtractor(FakeExtractor):
    """Reads household 1 off both of dwelling 6's cards."""

    def extract(self, image_path: Path) -> ExtractionResult:
        result = super().extract(image_path)
        result.fields["Number of Household"] = "1"
        return result


def test_a_shared_record_id_stays_null_until_a_correction_settles_it(tmp_path):
    scan_dir = _batch(tmp_path, _fixture_pages("r01", "r02"))

    def rerun(records):
        _write(tmp_path, records)
        run(
            scan_dir,
            region="north",
            extractor=SameHouseholdExtractor(),
            out_dir=tmp_path,
        )
        return _read(tmp_path)

    def ids(records):
        return [r["dwelling"]["households"][0]["record_id"] for r in records]

    records = rerun([])
    assert ids(records) == [None, None]
    assert all("duplicate_record_id" in r["dwelling"]["flags"] for r in records)

    # A correction elsewhere leaves the identity unsettled.
    head = records[0]["dwelling"]["households"][0]["head"]
    key = next(iter(head))
    head[key] = {**head[key], **CORRECTED}
    records = rerun(records)
    assert ids(records) == [None, None]

    # Correcting one household's number settles both.
    household = records[1]["dwelling"]["households"][0]
    household["household_no"] = {**household["household_no"], **CORRECTED}
    records = rerun(records)
    assert ids(records) == ["27-0006-01", "27-0006-02"]
    assert not any("duplicate_record_id" in r["dwelling"]["flags"] for r in records)


def test_a_shared_record_id_comes_back_once_the_other_is_corrected():
    def dwelling(page: int, municipality: str, **household) -> dict:
        field = {"value": None, "status": "ok", "confidence": None}
        return {
            "dwelling": {
                "municipality": {**field, "value": municipality},
                "dwelling_no": {**field, "value": "6"},
                "flags": ["duplicate_record_id"],
                "households": [
                    {
                        "record_id": None,
                        "household_no": {**field, "value": "1"},
                        "cards": [
                            {"role": "coding-front", "image": "unit.pdf", "page": page}
                        ],
                        **household,
                    }
                ],
            }
        }

    corrected = dwelling(5, "28")  # was 27, the shared 27-0006-01
    corrected["dwelling"]["municipality"]["origin"] = "corrected"
    merged = _merge([], [dwelling(3, "27"), corrected])

    assert [r["dwelling"]["households"][0]["record_id"] for r in merged] == [
        "27-0006-01",
        "28-0006-01",
    ]
    assert not any("flags" in r["dwelling"] for r in merged)


def test_an_interrupted_run_resumes_without_rereading_finished_cards(tmp_path):
    scan_dir = _batch(tmp_path, _fixture_pages("r01", "r02"))
    raw_dir = tmp_path / "raw"
    with pytest.raises(KeyboardInterrupt):
        run(
            scan_dir,
            region="north",
            extractor=KilledExtractor(),
            out_dir=tmp_path,
            raw_dir=raw_dir,
        )

    resumed = FakeExtractor()
    resumed.calls = 1  # number households on from the cached card's
    summary = run(
        scan_dir, region="north", extractor=resumed, out_dir=tmp_path, raw_dir=raw_dir
    )

    assert resumed.calls == 2  # one card read
    assert summary.records == 2


def test_a_fresh_run_reads_every_card_again_and_keeps_corrections(tmp_path):
    scan_dir = _batch(tmp_path, _fixture_pages("r01", "r02"))
    raw_dir = tmp_path / "raw"
    run(
        scan_dir,
        region="north",
        extractor=FakeExtractor(),
        out_dir=tmp_path,
        raw_dir=raw_dir,
    )
    records = _read(tmp_path)
    corrected = {**records[0]["dwelling"]["house"]["garden"], **CORRECTED}
    records[0]["dwelling"]["house"]["garden"] = corrected
    _write(tmp_path, records)

    fresh = FakeExtractor()
    summary = run(
        scan_dir,
        region="north",
        extractor=fresh,
        out_dir=tmp_path,
        raw_dir=raw_dir,
        fresh=True,
    )

    assert (fresh.calls, summary.records) == (2, 2)
    assert _read(tmp_path)[0]["dwelling"]["house"]["garden"] == corrected
    assert (raw_dir / f"{FakeExtractor.name}.previous").is_dir()


def test_an_interrupted_fresh_run_resumes_with_a_plain_rerun(tmp_path):
    scan_dir = _batch(tmp_path, _fixture_pages("r01", "r02"))
    raw_dir = tmp_path / "raw"
    kwargs = {"region": "north", "out_dir": tmp_path, "raw_dir": raw_dir}
    run(scan_dir, extractor=FakeExtractor(), **kwargs)
    with pytest.raises(KeyboardInterrupt):
        run(scan_dir, extractor=KilledExtractor(), fresh=True, **kwargs)

    resumed = FakeExtractor()
    summary = run(scan_dir, extractor=resumed, **kwargs)

    # Card 1 was re-read before the interrupt; only card 2 is bought again.
    assert (resumed.calls, summary.records) == (1, 2)


def test_a_correction_that_breaks_the_record_id_stops_the_run(tmp_path):
    scan_dir = _batch(tmp_path, _fixture_pages("r01"))
    run(scan_dir, region="north", extractor=FakeExtractor(), out_dir=tmp_path)
    records = _read(tmp_path)
    dwelling_no = records[0]["dwelling"]["dwelling_no"]
    records[0]["dwelling"]["dwelling_no"] = {
        **dwelling_no,
        **CORRECTED,
        "value": "12345",
        "original_value": dwelling_no["value"],
    }
    _write(tmp_path, records)
    before = (tmp_path / "north.jsonl").read_text()

    with pytest.raises(MergeRefused, match="unit.pdf p3: .*record_id"):
        run(scan_dir, region="north", extractor=FakeExtractor(), out_dir=tmp_path)

    assert (tmp_path / "north.jsonl").read_text() == before


def test_an_unusable_reading_is_kept_and_not_bought_again(tmp_path):
    scan_dir = _batch(tmp_path, _fixture_pages("r01", "r02"))
    raw_dir = tmp_path / "raw"
    run(
        scan_dir,
        region="north",
        extractor=UnreadableOnceExtractor(),
        out_dir=tmp_path,
        raw_dir=raw_dir,
    )

    cached = json.loads(
        (raw_dir / "gemini-3.5-flash-lite" / "unit_p0003.json").read_text()
    )
    assert cached["raw_text"] == "not json"

    again = FakeExtractor()
    summary = run(
        scan_dir, region="north", extractor=again, out_dir=tmp_path, raw_dir=raw_dir
    )

    assert again.calls == 0
    assert summary.failed_cards == 1 and summary.records == 1


def test_a_run_stops_after_three_failed_cards_and_keeps_earlier_records(
    tmp_path, caplog
):
    scan_dir = _batch(tmp_path, _fixture_pages("r01", "r02", "r03", "r04", "r05"))
    run(scan_dir, region="north", extractor=FakeExtractor(), out_dir=tmp_path)

    down = DownExtractor()
    with caplog.at_level(logging.ERROR):
        summary = run(scan_dir, region="north", extractor=down, out_dir=tmp_path)

    assert down.calls == summary.failed_cards == 3
    assert summary.records == len(_read(tmp_path)) == 5
    assert "3 cards failed in a row; stopping, rerun to resume" in caplog.text


def test_unusable_answers_do_not_stop_a_run(tmp_path):
    scan_dir = _batch(tmp_path, _fixture_pages("r01", "r02", "r03", "r04", "r05"))
    garbage = GarbageExtractor()

    summary = run(scan_dir, region="north", extractor=garbage, out_dir=tmp_path)

    assert garbage.calls == summary.failed_cards == 5


def test_a_success_resets_the_failure_streak(tmp_path):
    scan_dir = _batch(tmp_path, _fixture_pages("r01", "r02", "r03", "r04", "r05"))
    flaky = FlakyExtractor()

    run(scan_dir, region="north", extractor=flaky, out_dir=tmp_path)

    assert flaky.calls == 5


def _write(out_dir: Path, records: list[dict]) -> None:
    (out_dir / "north.jsonl").write_text("".join(json.dumps(r) + "\n" for r in records))


def _stub(*pages: int, **dwelling) -> dict:
    records = [
        build_record(
            {
                "Municipality": "27",
                "Number of Dwelling": "6",
                "Number of Household": str(p),
            },
            region="north",
            image="unit.pdf",
            page=p,
        )
        for p in pages
    ]
    record = records[0]
    record["dwelling"]["households"] = [r["dwelling"]["households"][0] for r in records]
    record["dwelling"].update(dwelling)
    return record


CORRECTED = {"value": "2", "status": "ok", "origin": "corrected", "original_value": "1"}


def test_rerunning_a_finished_batch_changes_nothing(tmp_path):
    scan_dir = _batch(tmp_path, _fixture_pages("r01", "r02"))
    raw_dir = tmp_path / "raw"
    run(
        scan_dir,
        region="north",
        extractor=FakeExtractor(),
        out_dir=tmp_path,
        raw_dir=raw_dir,
    )
    before = (tmp_path / "north.jsonl").read_bytes()

    again = FakeExtractor()
    run(scan_dir, region="north", extractor=again, out_dir=tmp_path, raw_dir=raw_dir)

    assert again.calls == 0
    assert (tmp_path / "north.jsonl").read_bytes() == before


def test_a_corrected_field_survives_a_rerun_that_reextracts(tmp_path):
    scan_dir = _batch(tmp_path, _fixture_pages("r01", "r02"))
    run(scan_dir, region="north", extractor=FakeExtractor(), out_dir=tmp_path)
    records = _read(tmp_path)
    corrected = {**records[0]["dwelling"]["house"]["garden"], **CORRECTED}
    records[0]["dwelling"]["house"]["garden"] = corrected
    _write(tmp_path, records)

    run(scan_dir, region="north", extractor=FakeExtractor(), out_dir=tmp_path)

    records = _read(tmp_path)
    assert len(records) == 2
    assert records[0]["dwelling"]["house"]["garden"] == corrected
    jsonschema.validate(records[0], SCHEMA)


def test_rerunning_with_saved_corrections_reads_no_card_again(tmp_path):
    # IT-114 AC3 (FR-18): corrections come back from the results file and the
    # readings from the cache, so re-exporting costs no extraction.
    scan_dir = _batch(tmp_path, _fixture_pages("r01", "r02"))
    raw_dir = tmp_path / "raw"
    run(
        scan_dir,
        region="north",
        extractor=FakeExtractor(),
        out_dir=tmp_path,
        raw_dir=raw_dir,
    )
    records = _read(tmp_path)
    corrected = {**records[0]["dwelling"]["house"]["garden"], **CORRECTED}
    records[0]["dwelling"]["house"]["garden"] = corrected
    _write(tmp_path, records)

    again = FakeExtractor()
    run(scan_dir, region="north", extractor=again, out_dir=tmp_path, raw_dir=raw_dir)

    assert again.calls == 0
    assert _read(tmp_path)[0]["dwelling"]["house"]["garden"] == corrected


def test_a_corrected_household_number_carries_its_record_id(tmp_path):
    scan_dir = _batch(tmp_path, _fixture_pages("r01", "r02"))
    run(scan_dir, region="north", extractor=FakeExtractor(), out_dir=tmp_path)
    records = _read(tmp_path)
    household = records[0]["dwelling"]["households"][0]
    corrected = {**household["household_no"], **CORRECTED, "original_value": "1"}
    household["household_no"] = corrected
    household["record_id"] = "27-0006-02"
    _write(tmp_path, records)

    run(scan_dir, region="north", extractor=FakeExtractor(), out_dir=tmp_path)

    household = _read(tmp_path)[0]["dwelling"]["households"][0]
    assert household["record_id"] == "27-0006-02"
    other = _read(tmp_path)[1]["dwelling"]["households"][0]
    assert other["record_id"] is None  # the uncorrected machine collision loses
    assert household["household_no"] == corrected


def test_a_damaged_results_file_stops_the_run_before_any_extraction(tmp_path):
    scan_dir = _batch(tmp_path, _fixture_pages("r01"))
    (tmp_path / "north.jsonl").write_text("not json\n")
    extractor = FakeExtractor()

    with pytest.raises(MergeRefused, match="north.jsonl line 1"):
        run(scan_dir, region="north", extractor=extractor, out_dir=tmp_path)

    assert extractor.calls == 0
    assert (tmp_path / "north.jsonl").read_text() == "not json\n"


@pytest.mark.parametrize(
    "line", ["null", "[]", '{"dwelling": {}}', "no-coding-card", "bare-value"]
)
def test_a_results_file_with_a_malformed_record_stops_the_run_before_extraction(
    tmp_path, line
):
    scan_dir = _batch(tmp_path, _fixture_pages("r01"))
    if line in ("no-coding-card", "bare-value"):
        run(scan_dir, region="north", extractor=FakeExtractor(), out_dir=tmp_path)
        record = _read(tmp_path)[0]
        if line == "bare-value":  # a hand edit that breaks the envelope (D025)
            record["dwelling"]["house"]["garden"] = "1"
        for card in record["dwelling"]["households"][0]["cards"]:
            if line == "no-coding-card" and card["role"] == "coding-front":
                card["role"] = "survey-front"
        line = json.dumps(record)
    (tmp_path / "north.jsonl").write_text(line + "\n")
    extractor = FakeExtractor()

    with pytest.raises(MergeRefused, match="north.jsonl line 1"):
        run(scan_dir, region="north", extractor=extractor, out_dir=tmp_path)

    assert extractor.calls == 0
    assert (tmp_path / "north.jsonl").read_text() == line + "\n"


def _plant_bare_value(monkeypatch) -> None:
    """Make every built record break the envelope, as a buggy extractor would."""
    build = association.build_record

    def broken(*args, **kwargs):
        record = build(*args, **kwargs)
        record["dwelling"]["house"]["stray"] = "1"  # a field _score doesn't visit
        return record

    monkeypatch.setattr(association, "build_record", broken)


def test_an_invalid_record_is_reported_and_not_written(tmp_path, monkeypatch, caplog):
    scan_dir = _batch(tmp_path, _fixture_pages("r01"))
    _plant_bare_value(monkeypatch)

    summary = run(scan_dir, region="north", extractor=FakeExtractor(), out_dir=tmp_path)

    assert (summary.invalid_records, summary.records) == (1, 0)
    assert _read(tmp_path) == []
    assert "unit.pdf p3: 27-0006-01 fails the schema" in caplog.text
    assert "dwelling/house/stray" in caplog.text


def test_an_invalid_rereading_keeps_the_previous_record(tmp_path, monkeypatch):
    scan_dir = _batch(tmp_path, _fixture_pages("r01", "r02"))
    run(scan_dir, region="north", extractor=FakeExtractor(), out_dir=tmp_path)
    before = (tmp_path / "north.jsonl").read_bytes()
    _plant_bare_value(monkeypatch)

    summary = run(scan_dir, region="north", extractor=FakeExtractor(), out_dir=tmp_path)

    assert summary.invalid_records == 2
    assert (tmp_path / "north.jsonl").read_bytes() == before


def test_a_damaged_saved_reading_is_read_again_not_fatal_to_its_pdf(tmp_path):
    scan_dir = _batch(tmp_path, _fixture_pages("r01", "r02"))
    raw_dir = tmp_path / "raw"
    run(
        scan_dir,
        region="north",
        extractor=FakeExtractor(),
        out_dir=tmp_path,
        raw_dir=raw_dir,
    )
    cache = raw_dir / "gemini-3.5-flash-lite"
    (cache / "unit_p0003.json").write_text("")
    (cache / "unit_p0007.json").write_text('{"bogus": 1}')

    again = FakeExtractor()
    summary = run(
        scan_dir, region="north", extractor=again, out_dir=tmp_path, raw_dir=raw_dir
    )

    assert again.calls == 2
    assert summary.failed_pdfs == 0
    assert summary.records == 2


class CorrectingExtractor(FakeExtractor):
    """A reviewer saves a correction while the run is under way."""

    def __init__(self, out_dir: Path, corrected: dict) -> None:
        super().__init__()
        self.out_dir, self.corrected = out_dir, corrected

    def extract(self, image_path: Path) -> ExtractionResult:
        if self.calls == 0:
            records = _read(self.out_dir)
            records[0]["dwelling"]["house"]["garden"] = self.corrected
            _write(self.out_dir, records)
        return super().extract(image_path)


def test_a_correction_saved_during_a_run_is_not_overwritten(tmp_path):
    scan_dir = _batch(tmp_path, _fixture_pages("r01", "r02"))
    run(scan_dir, region="north", extractor=FakeExtractor(), out_dir=tmp_path)
    garden = _read(tmp_path)[0]["dwelling"]["house"]["garden"]
    corrected = {**garden, **CORRECTED}

    run(
        scan_dir,
        region="north",
        extractor=CorrectingExtractor(tmp_path, corrected),
        out_dir=tmp_path,
    )

    assert _read(tmp_path)[0]["dwelling"]["house"]["garden"] == corrected


def test_a_blanked_household_number_keeps_the_record_id(tmp_path):
    scan_dir = _batch(tmp_path, _fixture_pages("r01", "r02"))
    run(scan_dir, region="north", extractor=FakeExtractor(), out_dir=tmp_path)
    records = _read(tmp_path)
    household = records[0]["dwelling"]["households"][0]
    corrected = {
        **household["household_no"],
        "value": None,
        "status": "no_data",
        "origin": "corrected",
        "original_value": "1",
    }
    household["household_no"] = corrected
    _write(tmp_path, records)

    run(scan_dir, region="north", extractor=FakeExtractor(), out_dir=tmp_path)

    household = _read(tmp_path)[0]["dwelling"]["households"][0]
    assert household["record_id"] == "27-0006-01"
    assert household["household_no"] == corrected


def test_a_results_file_with_a_bom_is_read_and_rerun(tmp_path):
    scan_dir = _batch(tmp_path, _fixture_pages("r01", "r02"))
    run(scan_dir, region="north", extractor=FakeExtractor(), out_dir=tmp_path)
    path = tmp_path / "north.jsonl"
    path.write_text("\ufeff" + path.read_text(), encoding="utf-8")

    summary = run(scan_dir, region="north", extractor=FakeExtractor(), out_dir=tmp_path)

    assert summary.records == 2


def test_merge_replaces_overlapping_records_and_keeps_the_rest():
    merged = _merge([_stub(3, old=True), _stub(9)], [_stub(3, 7)])

    assert merged == [_stub(3, 7), _stub(9)]


def test_merge_refuses_to_move_a_correction_onto_a_regrouped_record():
    with pytest.raises(MergeRefused, match="regrouped"):
        _merge([_stub(3, garden=CORRECTED)], [_stub(3, 7)])


def test_merge_refuses_a_corrected_note_whose_front_left_the_dwelling():
    """The main front read as this dwelling before and as another now: the
    coding card stays, but notes[0] is now the overflow sheet's back."""

    def front(page: int) -> dict:
        return {"role": "survey-front", "image": "unit.pdf", "page": page}

    other = {"page": 4, "front_page": 3, "text": {"value": "x", "status": "ok"}}
    main = {"page": 2, "front_page": 1, "text": CORRECTED}
    old = _stub(5, cards=[front(1), front(3)], notes=[main, other])
    new = _stub(5, cards=[front(3)], notes=[other])

    with pytest.raises(MergeRefused, match="dwelling/notes/0/text has no place"):
        _merge([old], [new])


def test_merge_refuses_a_correction_with_no_place_in_the_rebuilt_record():
    with pytest.raises(MergeRefused, match="dwelling/gone/x"):
        _merge([_stub(3, gone={"x": CORRECTED})], [_stub(3)])


def test_merge_refuses_a_correction_when_households_are_reordered():
    with pytest.raises(MergeRefused, match="regrouped"):
        _merge([_stub(3, 7, garden=CORRECTED)], [_stub(7, 3)])


def test_a_results_file_holding_another_regions_records_stops_the_run(tmp_path):
    scan_dir = _batch(tmp_path, _fixture_pages("r01"))
    run(scan_dir, region="north", extractor=FakeExtractor(), out_dir=tmp_path)
    # Renamed, or copied in from another machine's results/ under the wrong name.
    (tmp_path / "north.jsonl").rename(tmp_path / "south.jsonl")
    before = (tmp_path / "south.jsonl").read_bytes()
    extractor = FakeExtractor()

    with pytest.raises(
        MergeRefused, match="south.jsonl line 1: region 'north', not 'south'"
    ):
        run(scan_dir, region="south", extractor=extractor, out_dir=tmp_path)

    assert extractor.calls == 0
    assert (tmp_path / "south.jsonl").read_bytes() == before


def test_two_regions_write_their_own_files_and_never_touch_each_other(tmp_path):
    """FR-02 verification: >=2 region batches, partitioned, no cross-contamination."""
    out_dir, raw = tmp_path / "results", tmp_path / "raw"
    north = _batch(tmp_path, _fixture_pages("r01"), unit="216412")
    south = _batch(tmp_path, _fixture_pages("r02"), unit="216413")

    run(
        north,
        region="north",
        extractor=FakeExtractor(),
        out_dir=out_dir,
        raw_dir=raw / "north",
    )
    before = (out_dir / "north.jsonl").read_bytes()
    run(
        south,
        region="south",
        extractor=FakeExtractor(),
        out_dir=out_dir,
        raw_dir=raw / "south",
    )

    # AC2: the second run left the first region's output alone
    assert (out_dir / "north.jsonl").read_bytes() == before
    assert sorted(p.name for p in out_dir.iterdir()) == ["north.jsonl", "south.jsonl"]
    assert sorted(p.name for p in raw.iterdir()) == ["north", "south"]
    # AC1: every record in a file belongs to its region and its own scans
    keys = {}
    for region, pdf in [("north", "216412.pdf"), ("south", "216413.pdf")]:
        records = _read(out_dir, region)
        assert records
        assert {r["region"] for r in records} == {region}
        assert {r["batch"] for r in records} == {pdf}
        keys[region] = {c for r in records for c in pipeline._coding_cards(r)}
    # AC2: no record appears in both (D026 merge key: scan and page)
    assert not keys["north"] & keys["south"]


def test_a_region_with_no_coding_cards_does_not_publish_an_empty_file(tmp_path):
    pages = [FIXTURES / "r01-survey-front.jpg", FIXTURES / "r01-survey-back.jpg"]
    scan_dir = _batch(tmp_path, pages)

    summary = run(scan_dir, region="north", extractor=FakeExtractor(), out_dir=tmp_path)

    assert summary.records == 0
    assert not (tmp_path / "north.jsonl").exists()


def test_with_fronts_two_households_of_a_dwelling_share_one_line(tmp_path):
    scan_dir = _batch(tmp_path, _fixture_pages("r01", "r02"))
    raw_dir = tmp_path / "raw"

    summary = run(
        scan_dir,
        region="north",
        extractor=FakeExtractor(),
        front_extractor=FrontExtractor(),
        out_dir=tmp_path,
        raw_dir=raw_dir,
    )

    [record] = _read(tmp_path)
    jsonschema.validate(record, SCHEMA)
    assert summary.records == 1
    households = record["dwelling"]["households"]
    assert [h["record_id"] for h in households] == ["27-0006-01", "27-0006-02"]
    # D026: each card named by its PDF and PDF page, not a temporary image
    cards = [h["cards"][0] for h in households]
    assert [(c["image"], c["page"]) for c in cards] == [
        ("unit.pdf", 3),
        ("unit.pdf", 7),
    ]
    assert all(isinstance(c["confidence"], float) for c in cards)
    fronts = record["dwelling"]["cards"]
    assert [(c["image"], c["page"]) for c in fronts] == [
        ("unit.pdf", 1),
        ("unit.pdf", 5),
    ]
    assert record["dwelling"]["address"]["value"] == "6 Hall St."
    assert sorted(p.name for p in raw_dir.iterdir()) == [
        "gemini-3.5-flash-lite",
        "gemini-3.5-flash-lite-survey-front",
    ]


def test_a_correction_on_a_second_household_survives_a_rerun(tmp_path):
    scan_dir = _batch(tmp_path, _fixture_pages("r01", "r02"))
    fronts = {"extractor": FakeExtractor(), "front_extractor": FrontExtractor()}
    run(scan_dir, region="north", out_dir=tmp_path, **fronts)
    records = _read(tmp_path)
    head = records[0]["dwelling"]["households"][1]["head"]
    key = next(iter(head))
    corrected = {**head[key], **CORRECTED}
    head[key] = corrected
    _write(tmp_path, records)

    fronts = {"extractor": FakeExtractor(), "front_extractor": FrontExtractor()}
    run(scan_dir, region="north", out_dir=tmp_path, **fronts)

    [record] = _read(tmp_path)
    assert record["dwelling"]["households"][1]["head"][key] == corrected
    jsonschema.validate(record, SCHEMA)


def test_a_dwelling_with_a_failed_card_keeps_its_previous_line(tmp_path):
    """Rebuilt without the failed household, it would replace the full one."""
    scan_dir = _batch(tmp_path, _fixture_pages("r01", "r02"))
    run(
        scan_dir,
        region="north",
        extractor=FakeExtractor(),
        front_extractor=FrontExtractor(),
        out_dir=tmp_path,
    )
    before = (tmp_path / "north.jsonl").read_bytes()

    summary = run(
        scan_dir,
        region="north",
        extractor=FakeExtractor(fail_on=2),
        front_extractor=FrontExtractor(),
        out_dir=tmp_path,
    )

    assert summary.failed_cards == 1
    assert (tmp_path / "north.jsonl").read_bytes() == before


class FailingFrontExtractor(FrontExtractor):
    def extract(self, image_path: Path) -> ExtractionResult:
        raise RuntimeError("429 quota")


def test_a_rerun_whose_fronts_fail_keeps_the_previous_line(tmp_path):
    """Unread fronts have no dwelling number, so the dwelling would split."""
    scan_dir = _batch(tmp_path, _fixture_pages("r01", "r02"))
    run(
        scan_dir,
        region="north",
        extractor=FakeExtractor(),
        front_extractor=FrontExtractor(),
        out_dir=tmp_path,
    )
    before = (tmp_path / "north.jsonl").read_bytes()

    summary = run(
        scan_dir,
        region="north",
        extractor=FakeExtractor(),
        front_extractor=FailingFrontExtractor(),
        out_dir=tmp_path,
    )

    assert summary.failed_cards == 2
    assert (tmp_path / "north.jsonl").read_bytes() == before


def test_a_dwelling_rebuilt_in_part_does_not_replace_the_whole_one(tmp_path):
    scan_dir = _batch(tmp_path, _fixture_pages("r01", "r02"))
    fronts = {"extractor": FakeExtractor(), "front_extractor": FrontExtractor()}
    run(scan_dir, region="north", out_dir=tmp_path, **fronts)
    [whole] = _read(tmp_path)
    part = json.loads(json.dumps(whole))
    del part["dwelling"]["households"][1]

    assert _merge([whole], [part]) == [whole]


class DwellingPerCardExtractor(FakeExtractor):
    """Reads r01's coding card as dwelling 6 and r02's as dwelling 7."""

    def extract(self, image_path: Path) -> ExtractionResult:
        result = super().extract(image_path)
        fields = {**result.fields, "Number of Household": "1"}
        fields["Number of Dwelling"] = str(5 + self.calls)
        return ExtractionResult(fields=fields, raw_text=result.raw_text)


class UnusableFirstFrontExtractor(FrontExtractor):
    """r01's front comes back unparseable; r02's reads as dwelling 7."""

    def extract(self, image_path: Path) -> ExtractionResult:
        self.calls += 1
        if self.calls == 1:
            return ExtractionResult(raw_text="not json")
        fields = {"Dwelling Number (top-left corner)": "7", "Address": "7 Hall St."}
        return ExtractionResult(fields=fields, raw_text=json.dumps(fields))


def test_an_unusable_front_still_writes_its_household_on_every_run(tmp_path):
    """The bad reading is cached, so dropping its dwelling would be for good."""
    scan_dir = _batch(tmp_path, _fixture_pages("r01", "r02"))
    raw_dir = tmp_path / "raw"
    front = UnusableFirstFrontExtractor()

    for _ in range(2):  # the second run replays the cached readings
        summary = run(
            scan_dir,
            region="north",
            extractor=DwellingPerCardExtractor(),
            front_extractor=front,
            out_dir=tmp_path,
            raw_dir=raw_dir,
        )

        records = _read(tmp_path)
        assert [r["dwelling"]["households"][0]["record_id"] for r in records] == [
            "27-0006-01",
            "27-0007-01",
        ]
        assert summary.failed_cards == 1
        assert records[0]["dwelling"]["address"]["status"] == "omitted"
        assert records[1]["dwelling"]["address"]["value"] == "7 Hall St."
        for record in records:
            jsonschema.validate(record, SCHEMA)
        assert front.calls == 2  # the unusable reading is not paid for again


class UnusableFrontExtractor(FrontExtractor):
    def extract(self, image_path: Path) -> ExtractionResult:
        self.calls += 1
        return ExtractionResult(raw_text="not json")


class NotesExtractor(FakeExtractor):
    """Reads every survey back as ``notes``; ``fail`` raises instead."""

    name = "gemini-3.5-flash-lite-reverse-notes"

    def __init__(self, notes: str = "Very big house.", fail: bool = False) -> None:
        super().__init__()
        self.notes, self.fail = notes, fail

    def extract(self, image_path: Path) -> ExtractionResult:
        self.calls += 1
        if self.fail:
            raise RuntimeError("429 quota")
        fields = {"Interview Notes": self.notes}
        return ExtractionResult(fields=fields, raw_text=json.dumps(fields))


def _with_notes(notes: FakeExtractor | None = None) -> dict:
    return {
        "region": "north",
        "extractor": FakeExtractor(),
        "front_extractor": FrontExtractor(),
        "notes_extractor": notes or NotesExtractor(),
    }


def test_each_back_is_read_and_its_notes_written_on_the_dwelling(tmp_path):
    """FR-05 end to end: AC1's text, AC2's household, AC4's scan and page."""
    scan_dir = _batch(tmp_path, _fixture_pages("r01"))
    raw_dir = tmp_path / "raw"

    summary = run(scan_dir, out_dir=tmp_path, raw_dir=raw_dir, **_with_notes())

    [record] = _read(tmp_path)
    jsonschema.validate(record, SCHEMA)
    [note] = record["dwelling"]["notes"]
    assert (note["text"]["value"], note["text"]["status"]) == ("Very big house.", "ok")
    assert (note["page"], note["household_id"]) == (2, "27-0006-01")
    assert [
        (c["role"], c["image"], c["page"]) for c in record["dwelling"]["cards"]
    ] == [
        ("survey-front", "unit.pdf", 1),
        ("survey-back", "unit.pdf", 2),
    ]
    assert summary.failed_cards == summary.unattached_notes == 0
    notes_cache = raw_dir / "gemini-3.5-flash-lite-reverse-notes"
    assert [p.name for p in notes_cache.iterdir()] == ["unit_p0002.json"]


def test_a_blank_back_is_an_explicit_empty_and_not_a_failure(tmp_path):
    """AC3."""
    scan_dir = _batch(tmp_path, _fixture_pages("r01"))

    summary = run(scan_dir, out_dir=tmp_path, **_with_notes(NotesExtractor(notes="")))

    [record] = _read(tmp_path)
    [note] = record["dwelling"]["notes"]
    assert (note["text"]["status"], note["text"]["value"]) == ("no_data", None)
    assert summary.failed_cards == 0
    jsonschema.validate(record, SCHEMA)


def test_without_fronts_notes_cannot_be_placed():
    with pytest.raises(ValueError, match="front_extractor"):
        run(
            Path("unused"),
            region="north",
            extractor=FakeExtractor(),
            out_dir=Path("unused"),
            notes_extractor=NotesExtractor(),
        )


def test_a_rerun_replays_cached_notes_and_changes_nothing(tmp_path):
    scan_dir = _batch(tmp_path, _fixture_pages("r01"))
    raw_dir = tmp_path / "raw"
    run(scan_dir, out_dir=tmp_path, raw_dir=raw_dir, **_with_notes())
    before = (tmp_path / "north.jsonl").read_bytes()

    again = NotesExtractor()
    run(scan_dir, out_dir=tmp_path, raw_dir=raw_dir, **_with_notes(again))

    assert again.calls == 0
    assert (tmp_path / "north.jsonl").read_bytes() == before


def test_a_rerun_without_notes_keeps_the_notes_read_before(tmp_path):
    scan_dir = _batch(tmp_path, _fixture_pages("r01"))
    run(scan_dir, out_dir=tmp_path, **_with_notes())
    before = (tmp_path / "north.jsonl").read_bytes()

    run(
        scan_dir,
        region="north",
        extractor=FakeExtractor(),
        front_extractor=FrontExtractor(),
        out_dir=tmp_path,
    )

    assert (tmp_path / "north.jsonl").read_bytes() == before


def test_a_back_that_fails_now_keeps_the_notes_read_before(tmp_path):
    scan_dir = _batch(tmp_path, _fixture_pages("r01"))
    run(scan_dir, out_dir=tmp_path, **_with_notes())
    before = (tmp_path / "north.jsonl").read_bytes()

    summary = run(scan_dir, out_dir=tmp_path, **_with_notes(NotesExtractor(fail=True)))

    assert summary.failed_cards == 1
    assert (tmp_path / "north.jsonl").read_bytes() == before


def test_a_corrected_note_survives_a_rerun_that_rereads_it(tmp_path):
    scan_dir = _batch(tmp_path, _fixture_pages("r01"))
    run(scan_dir, out_dir=tmp_path, **_with_notes())
    records = _read(tmp_path)
    text = records[0]["dwelling"]["notes"][0]["text"]
    corrected = {
        **text,
        "value": "Very big house!",
        "origin": "corrected",
        "original_value": text["value"],
    }
    records[0]["dwelling"]["notes"][0]["text"] = corrected
    _write(tmp_path, records)

    run(scan_dir, out_dir=tmp_path, **_with_notes())

    [record] = _read(tmp_path)
    assert record["dwelling"]["notes"][0]["text"] == corrected
    jsonschema.validate(record, SCHEMA)


def test_a_corrected_note_follows_its_front_when_a_front_is_gained(tmp_path):
    """An overflow front joining the dwelling (IT-128) puts its back's note
    first, so the correction has to follow its front, not stay at index 0."""
    scan_dir = _batch(tmp_path, _fixture_pages("r01"))
    run(scan_dir, out_dir=tmp_path, **_with_notes())
    [old], [new] = _read(tmp_path), _read(tmp_path)
    text = old["dwelling"]["notes"][0]["text"]
    corrected = {**text, "origin": "corrected", "original_value": text["value"]}
    old["dwelling"]["notes"][0]["text"] = corrected
    dwelling = new["dwelling"]
    dwelling["cards"].append({**dwelling["cards"][0], "page": 3})
    dwelling["notes"].insert(0, {**dwelling["notes"][0], "page": 4, "front_page": 3})

    [merged] = _merge([old], [new])

    assert [
        (n["page"], n["text"] == corrected) for n in merged["dwelling"]["notes"]
    ] == [
        (4, False),
        (2, True),
    ]


def test_a_corrected_household_number_moves_its_note_too(tmp_path):
    """The correction rebuilds record_id; the note must name the new one."""
    scan_dir = _batch(tmp_path, _fixture_pages("r01"))
    run(scan_dir, out_dir=tmp_path, **_with_notes())
    records = _read(tmp_path)
    household = records[0]["dwelling"]["households"][0]
    number = household["household_no"]
    household["household_no"] = {
        **number,
        "value": "02",
        "origin": "corrected",
        "original_value": number["value"],
    }
    _write(tmp_path, records)

    run(scan_dir, out_dir=tmp_path, **_with_notes())

    [record] = _read(tmp_path)
    [note] = record["dwelling"]["notes"]
    assert note["household_id"] == record["dwelling"]["households"][0]["record_id"]
    assert note["household_id"] == "27-0006-02"
    jsonschema.validate(record, SCHEMA)


def test_notes_kept_from_before_name_no_household_once_a_second_joins():
    front = {"role": "survey-front", "image": "unit.pdf", "page": 1}
    note = {
        "page": 2,
        "front_page": 1,
        "text": {"value": "x", "status": "ok"},
        "household_id": "27-0006-03",
    }
    old = _stub(3, cards=[front], notes=[note])
    new = _stub(3, 7, cards=[front])
    [merged] = _merge([old], [new])

    [kept] = merged["dwelling"]["notes"]
    assert (kept["household_id"], kept["flags"]) == (None, ["household_ambiguous"])


def _back_not_found(record: dict) -> dict:
    """The same record as a rerun that found no back behind its front."""
    rerun = json.loads(json.dumps(record))
    dwelling = rerun["dwelling"]
    dwelling["cards"] = [c for c in dwelling["cards"] if c["role"] != "survey-back"]
    for note in dwelling["notes"]:
        note.update(page=None, text=build_omitted_field(), flags=["no_reverse_found"])
    return rerun


def test_a_back_not_found_now_keeps_the_notes_read_before(tmp_path):
    scan_dir = _batch(tmp_path, _fixture_pages("r01"))
    run(scan_dir, out_dir=tmp_path, **_with_notes())
    [old] = _read(tmp_path)

    [merged] = _merge([old], [_back_not_found(old)])

    assert merged == old


def test_a_corrected_note_survives_a_rerun_that_finds_no_back(tmp_path):
    scan_dir = _batch(tmp_path, _fixture_pages("r01"))
    run(scan_dir, out_dir=tmp_path, **_with_notes())
    [old] = _read(tmp_path)
    text = old["dwelling"]["notes"][0]["text"]
    corrected = {**text, "origin": "corrected", "original_value": text["value"]}
    old["dwelling"]["notes"][0]["text"] = corrected

    [merged] = _merge([old], [_back_not_found(old)])

    [note] = merged["dwelling"]["notes"]
    assert (note["page"], note["text"]) == (2, corrected)
    jsonschema.validate(merged, SCHEMA)


def test_a_rerun_without_notes_keeps_notes_when_a_front_is_gained(tmp_path):
    scan_dir = _batch(tmp_path, _fixture_pages("r01"))
    run(scan_dir, out_dir=tmp_path, **_with_notes())
    [old], [new] = _read(tmp_path), _read(tmp_path)
    dwelling = new["dwelling"]
    del dwelling["notes"]
    front = dwelling["cards"][0]
    dwelling["cards"] = [front, {**front, "page": 3}]

    [merged] = _merge([old], [new])

    assert merged["dwelling"]["notes"] == old["dwelling"]["notes"]
    assert [(c["role"], c["page"]) for c in merged["dwelling"]["cards"]] == [
        ("survey-front", 1),
        ("survey-back", 2),
        ("survey-front", 3),
    ]


def test_a_different_back_now_does_not_take_the_old_notes(tmp_path):
    scan_dir = _batch(tmp_path, _fixture_pages("r01"))
    run(scan_dir, out_dir=tmp_path, **_with_notes())
    [old], [new] = _read(tmp_path), _read(tmp_path)
    dwelling = new["dwelling"]
    dwelling["cards"][1]["page"] = 4
    dwelling["notes"][0].update(page=4, text=build_omitted_field(source="survey-back"))

    [merged] = _merge([old], [new])

    [note] = merged["dwelling"]["notes"]
    assert (note["page"], note["text"]["status"]) == (4, "omitted")


def test_notes_whose_front_left_the_dwelling_are_logged_not_kept(tmp_path, caplog):
    scan_dir = _batch(tmp_path, _fixture_pages("r01"))
    run(scan_dir, out_dir=tmp_path, **_with_notes())
    [old], [new] = _read(tmp_path), _read(tmp_path)
    dwelling = new["dwelling"]
    del dwelling["notes"]
    dwelling["cards"] = [{**dwelling["cards"][0], "page": 3}]

    [merged] = _merge([old], [new])

    assert "notes" not in merged["dwelling"]
    assert "unit.pdf p1: front left the dwelling" in caplog.text


def test_three_failed_backs_stop_the_run(tmp_path):
    """Four fronts all read as dwelling 6, so one dwelling with four backs."""
    scan_dir = _batch(tmp_path, _fixture_pages("r01", "r02", "r03", "r04"))
    notes = NotesExtractor(fail=True)

    summary = run(scan_dir, out_dir=tmp_path, **_with_notes(notes))

    assert notes.calls == MAX_FAILURE_STREAK == 3
    assert summary.failed_cards == 3
    [record] = _read(tmp_path)
    assert [n["text"]["status"] for n in record["dwelling"]["notes"]] == ["omitted"] * 4


def test_a_fresh_rerun_with_an_unusable_front_keeps_the_previous_reading(tmp_path):
    scan_dir = _batch(tmp_path, _fixture_pages("r01"))
    raw_dir = tmp_path / "raw"
    coding = FakeExtractor()
    run(
        scan_dir,
        region="north",
        extractor=coding,
        out_dir=tmp_path,
        front_extractor=FrontExtractor(),
        raw_dir=raw_dir,
    )
    [before] = _read(tmp_path)

    summary = run(
        scan_dir,
        region="north",
        extractor=FakeExtractor(),
        front_extractor=UnusableFrontExtractor(),
        out_dir=tmp_path,
        raw_dir=raw_dir,
        fresh=True,
    )

    [after] = _read(tmp_path)
    assert summary.failed_cards == 1
    assert after["dwelling"]["address"]["value"] == "6 Hall St."
    assert after == before


def test_a_fresh_rerun_without_notes_and_an_unusable_front_keeps_both(tmp_path):
    """The backs' card entries, there before and not now, are not a regrouping."""
    scan_dir = _batch(tmp_path, _fixture_pages("r01"))
    raw_dir = tmp_path / "raw"
    run(scan_dir, out_dir=tmp_path, raw_dir=raw_dir, **_with_notes())
    [before] = _read(tmp_path)

    run(
        scan_dir,
        region="north",
        extractor=FakeExtractor(),
        front_extractor=UnusableFrontExtractor(),
        out_dir=tmp_path,
        raw_dir=raw_dir,
        fresh=True,
    )

    [after] = _read(tmp_path)
    assert after["dwelling"]["address"]["value"] == "6 Hall St."
    assert after["dwelling"]["notes"] == before["dwelling"]["notes"]
    assert after == before


# --- IT-124: excluded sources, misspelt labels, configuration ----------------

EXCLUDED = {("unit.pdf", 7)}


def _pages(records: list[dict]) -> list[list[int]]:
    return [
        sorted(c["page"] for h in r["dwelling"]["households"] for c in h["cards"])
        for r in records
    ]


def test_an_excluded_page_is_never_read_and_its_old_record_goes(tmp_path):
    scan_dir = _batch(tmp_path, _fixture_pages("r01", "r02"))
    raw_dir = tmp_path / "raw"
    run(scan_dir, region="north", extractor=FakeExtractor(), out_dir=tmp_path)
    assert _pages(_read(tmp_path)) == [[3], [7]]

    fresh = FakeExtractor()
    summary = run(
        scan_dir,
        region="north",
        extractor=fresh,
        out_dir=tmp_path,
        raw_dir=raw_dir,
        fresh=True,
        excluded_sources=EXCLUDED,
    )
    assert fresh.calls == 1  # page 3 only
    assert summary.excluded_pages == 1 and summary.failed_cards == 0
    assert _pages(_read(tmp_path)) == [[3]]
    before = (tmp_path / "north.jsonl").read_bytes()

    # A rerun can't bring it back, and rebuilding again changes nothing.
    again = FakeExtractor()
    run(
        scan_dir,
        region="north",
        extractor=again,
        out_dir=tmp_path,
        raw_dir=raw_dir,
        excluded_sources=EXCLUDED,
    )
    assert again.calls == 0
    assert (tmp_path / "north.jsonl").read_bytes() == before


def test_a_correction_on_a_kept_source_survives_an_exclusion(tmp_path):
    scan_dir = _batch(tmp_path, _fixture_pages("r01", "r02"))
    run(scan_dir, region="north", extractor=FakeExtractor(), out_dir=tmp_path)
    records = _read(tmp_path)
    corrected = {**records[0]["dwelling"]["house"]["garden"], **CORRECTED}
    records[0]["dwelling"]["house"]["garden"] = corrected
    _write(tmp_path, records)

    run(
        scan_dir,
        region="north",
        extractor=FakeExtractor(),
        out_dir=tmp_path,
        excluded_sources=EXCLUDED,
    )

    (record,) = _read(tmp_path)
    assert record["dwelling"]["house"]["garden"] == corrected
    jsonschema.validate(record, SCHEMA)


def test_excluding_a_reviewed_record_is_refused(tmp_path):
    scan_dir = _batch(tmp_path, _fixture_pages("r01", "r02"))
    run(scan_dir, region="north", extractor=FakeExtractor(), out_dir=tmp_path)
    records = _read(tmp_path)
    records[1]["dwelling"]["house"]["garden"].update(CORRECTED)
    _write(tmp_path, records)
    before = (tmp_path / "north.jsonl").read_bytes()

    extractor = FakeExtractor()
    with pytest.raises(MergeRefused, match="reviewed"):
        run(
            scan_dir,
            region="north",
            extractor=extractor,
            out_dir=tmp_path,
            excluded_sources=EXCLUDED,
        )
    assert extractor.calls == 0  # refused before anything was read
    assert (tmp_path / "north.jsonl").read_bytes() == before


def test_excluding_part_of_a_dwelling_is_refused(tmp_path):
    scan_dir = _batch(tmp_path, _fixture_pages("r01", "r02"))
    _write(tmp_path, [_stub(3, 7)])
    before = (tmp_path / "north.jsonl").read_bytes()

    with pytest.raises(MergeRefused, match="also holds unit.pdf p3"):
        run(
            scan_dir,
            region="north",
            extractor=FakeExtractor(),
            out_dir=tmp_path,
            excluded_sources=EXCLUDED,
        )
    assert (tmp_path / "north.jsonl").read_bytes() == before


def test_a_page_cannot_be_both_verified_coding_and_excluded(tmp_path):
    scan_dir = _batch(tmp_path, _fixture_pages("r01"))
    with pytest.raises(MergeRefused, match="unit.pdf p7"):
        run(
            scan_dir,
            region="north",
            extractor=FakeExtractor(),
            out_dir=tmp_path,
            verified_coding=EXCLUDED,
            excluded_sources=EXCLUDED,
        )


class StaleQwenExtractor(FakeExtractor):
    """A reading parsed before the aliases: the reply says Washhouse, and its
    fields, like every cached Qwen reading from IT-124, don't have Washouse."""

    name = model_id = "qwen2.5-vl"
    reply: ClassVar[dict] = {
        "Washhouse": {"value": "2", "struck": True},
        "Pre-war Occupation": "07",
    }

    def extract(self, image_path: Path) -> ExtractionResult:
        result = super().extract(image_path)
        raw = {**json.loads(result.raw_text), **self.reply}
        fields = {**result.fields, "Washhouse": "2", "Pre-war Occupation": "07"}
        return ExtractionResult(fields=fields, raw_text=json.dumps(raw), struck={})


def test_a_misspelt_label_is_exported_under_the_schemas(tmp_path):
    scan_dir = _batch(tmp_path, _fixture_pages("r01"))
    run(
        scan_dir,
        region="north",
        extractor=StaleQwenExtractor(),
        out_dir=tmp_path,
        raw_dir=tmp_path / "raw",
    )
    (record,) = _read(tmp_path)
    washouse = record["dwelling"]["house"]["washouse"]
    # its own strike came with it (D023: struck empties the value)
    assert (washouse["status"], washouse["negated"]) == ("no_data", True)
    head = record["dwelling"]["households"][0]["head"]
    assert head["pre_war_occupation"]["value"] == "07"
    assert record["dwelling"]["house"]["bathroom"]["status"] == "omitted"
    jsonschema.validate(record, SCHEMA)


class ExplicitBlankExtractor(StaleQwenExtractor):
    reply: ClassVar[dict] = {"Washouse": None, "Washhouse": "2"}

    def extract(self, image_path: Path) -> ExtractionResult:
        result = super().extract(image_path)
        return ExtractionResult(
            fields={**result.fields, "Washouse": ""}, raw_text=result.raw_text
        )


def test_an_explicit_canonical_blank_beats_a_misspelt_value(tmp_path):
    scan_dir = _batch(tmp_path, _fixture_pages("r01"))
    run(scan_dir, region="north", extractor=ExplicitBlankExtractor(), out_dir=tmp_path)
    (record,) = _read(tmp_path)
    assert record["dwelling"]["house"]["washouse"]["status"] == "no_data"


class ConfiguredExtractor(FakeExtractor):
    name = cache_name = "qwen2.5-vl-server"
    model_id = "qwen2.5-vl"

    def __init__(self, weights: str = "Q6_K") -> None:
        super().__init__()
        self.config = {"model": "qwen/qwen2.5-vl-7b", "weights": weights}


def test_a_run_refuses_results_made_with_another_configuration(tmp_path):
    scan_dir = _batch(tmp_path, _fixture_pages("r01"))
    out_dir, raw_dir = tmp_path / "out", tmp_path / "raw"
    run(
        scan_dir,
        region="north",
        extractor=ConfiguredExtractor(),
        out_dir=out_dir,
        raw_dir=raw_dir,
    )
    recorded = {"model": "qwen/qwen2.5-vl-7b", "weights": "Q6_K"}
    for folder in (out_dir, raw_dir / "qwen2.5-vl-server"):
        assert json.loads((folder / "extractor.json").read_text()) == recorded
    before = (out_dir / "north.jsonl").read_bytes()

    other = ConfiguredExtractor("Q4_K_M")
    with pytest.raises(MergeRefused, match="weights: 'Q6_K' now 'Q4_K_M'"):
        run(
            scan_dir,
            region="north",
            extractor=other,
            out_dir=out_dir,
            raw_dir=raw_dir,
        )
    assert other.calls == 0
    assert (out_dir / "north.jsonl").read_bytes() == before

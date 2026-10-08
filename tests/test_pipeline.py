"""FR-17: a fixture batch runs end to end (AC1) and an unrecognised page is
skipped while the rest are processed (AC2).

The batch PDF is built in tmp_path from tests/fixtures/, and the extractor is a
fake, so nothing here touches data/ or calls Gemini.
"""

import json
import logging
from pathlib import Path

import jsonschema
import numpy as np
import pytest
from PIL import Image

from survey import pipeline
from survey.association import records as association
from survey.extraction.base import ExtractionResult
from survey.pipeline import MergeRefused, _merge, run

FIXTURES = Path(__file__).parent / "fixtures"
SCHEMA = json.loads(
    (Path(__file__).parent.parent / "schema/record-envelope.schema.json").read_text()
)
ROLES = ["survey-front", "survey-back", "coding-front", "coding-back"]


class FakeExtractor:
    """Reads every coding card as municipality 27, dwelling 6, next household."""

    name = model_id = "gemini-3.5-flash-lite"

    def __init__(self, fail_on: int | None = None) -> None:
        self.calls = 0
        self.fail_on = fail_on

    def is_available(self) -> bool:
        return True

    def extract(self, image_path: Path) -> ExtractionResult:
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
    """Inked but unruled, landing third in a reverse/coding run (FR-21)."""
    rng = np.random.default_rng(0)
    pixels = np.where(rng.random((500, 800)) < 0.06, 0, 255).astype("uint8")
    path = tmp_path / "stray.jpg"
    Image.fromarray(pixels, mode="L").save(path)
    return path


def _read(out_dir: Path, region: str = "north") -> list[dict]:
    return [json.loads(line) for line in (out_dir / f"{region}.jsonl").open()]


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


def test_a_card_with_no_readable_identity_is_skipped(tmp_path, caplog):
    scan_dir = _batch(tmp_path, _fixture_pages("r01", "r02"))

    with caplog.at_level(logging.WARNING):
        summary = run(
            scan_dir,
            region="north",
            extractor=NoHouseholdExtractor(),
            out_dir=tmp_path,
        )

    assert summary.unreadable_cards == 1
    assert [r["dwelling"]["households"][0]["record_id"] for r in _read(tmp_path)] == [
        "27-0006-02"
    ]
    assert "unit.pdf p3: cannot build record_id without Number of Household" in (
        caplog.text
    )


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
    households = [
        {"cards": [{"role": "coding-front", "image": "unit.pdf", "page": p}]}
        for p in pages
    ]
    return {"dwelling": {"households": households, **dwelling}}


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


def test_a_region_with_no_coding_cards_still_writes_its_empty_file(tmp_path):
    pages = [FIXTURES / "r01-survey-front.jpg", FIXTURES / "r01-survey-back.jpg"]
    scan_dir = _batch(tmp_path, pages)

    summary = run(scan_dir, region="north", extractor=FakeExtractor(), out_dir=tmp_path)

    assert summary.records == 0
    assert (tmp_path / "north.jsonl").read_text() == ""


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

    for _ in range(2):  # the second run replays the cached readings
        summary = run(
            scan_dir,
            region="north",
            extractor=DwellingPerCardExtractor(),
            front_extractor=UnusableFirstFrontExtractor(),
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

"""Offline merge invariants and real review-service audit preservation."""

import json
from copy import deepcopy
from dataclasses import asdict, replace

import pytest
import review_support
from review_support import decide, refs, setup_review

from survey.confidence.card import card_confidence
from survey.extraction.base import ExtractionResult
from survey.extraction.card_fields import FIELD_SCHEMA
from survey.extraction.record import build_record
from survey.merge_runs import cache_reading, merge_region, score_household
from survey.records import validate_records


@pytest.fixture
def prepared(monkeypatch):
    """Merges read only prepared 0.7.0 data."""
    monkeypatch.setattr(review_support, "PREPARED", True)


def reading(**updates):
    fields = {s.name: "1" for s in FIELD_SCHEMA}
    fields.update(
        {"Municipality": "27", "Number of Dwelling": "6", "Number of Household": "1"}
    )
    fields.update(updates)
    return ExtractionResult(fields=fields)


def cached(folder, result, page=1):
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"synthetic_p{page:04d}.json").write_text(json.dumps(asdict(result)))


def single(a):
    return build_record(
        a.fields, region="demo", image="synthetic.pdf", page=1, struck=None
    )


def test_second_household_uses_own_shared_raw_fields():
    a = reading(**{"Number of Household": "2", "Garden": "2"})
    b = reading(**{"Number of Household": "2", "Garden": "1"})
    r = single(reading())
    h = single(a)["dwelling"]["households"][0]
    h["cards"][0]["page"] = 2
    r["dwelling"]["households"].append(h)
    pairs, scores, _ = score_household(r, 1, a, b)
    assert pairs["Garden"]["a"] == "2"
    assert scores["Garden"]["source_agreement"] == "disagree"
    assert r["dwelling"]["households"][0]["house"]["garden"]["value"] == "1"
    # a later card scores its own dwelling_no and house fields (0.7.0)
    assert h["house"]["garden"]["confidence"] == scores["Garden"]["confidence"]
    assert h["dwelling_no"]["confidence"] == scores["Number of Dwelling"]["confidence"]
    assert "Number of Dwelling" in pairs
    assert h["cards"][0]["confidence"] == card_confidence(
        s["confidence"] for s in scores.values()
    )


def test_explicit_gemini_blank_and_omission_never_take_qwen():
    a = reading(Garden="")
    del a.fields["Washouse"]
    r = single(a)
    _, scores, _ = score_household(r, 0, a, reading())
    assert r["dwelling"]["households"][0]["house"]["garden"]["value"] is None
    assert scores["Garden"]["source_agreement"] == "one_blank"
    assert r["dwelling"]["households"][0]["house"]["washouse"]["status"] == "omitted"
    assert scores["Washouse"]["confidence"] == 0.0


def test_only_whole_gemini_failure_substitutes_qwen():
    r = single(reading())
    score_household(r, 0, None, reading(Garden="2"), first_state="failed")
    assert r["dwelling"]["households"][0]["house"]["garden"]["value"] == "2"
    assert r["dwelling"]["households"][0]["house"]["garden"]["confidence"] == 0.85


def test_missing_qwen_scores_primary_and_failure_stays_distinct(tmp_path):
    a = reading()
    cached(tmp_path / "a", a)
    merged, audit = merge_region(
        "demo",
        [single(a)],
        tmp_path / "a",
        tmp_path / "b",
        {("demo", "synthetic.pdf", 1)},
    )
    assert audit[0]["secondary_state"] == "failed"
    assert {s["source_agreement"] for s in audit[0]["fields"].values()} == {
        "no_second_opinion"
    }
    assert (
        merged[0]["dwelling"]["households"][0]["house"]["garden"]["confidence"] == 0.91
    )
    assert cache_reading(tmp_path / "absent.json")[1] == "absent"
    cached(tmp_path / "failed", ExtractionResult())
    assert cache_reading(tmp_path / "failed/synthetic_p0001.json")[1] == "failed"


def test_primary_alias_fill_only_changes_unreviewed_omission(tmp_path):
    a = reading()
    old = reading()
    del old.fields["Washouse"]
    r = single(old)
    cached(tmp_path / "a", a)
    cached(tmp_path / "b", a)
    merged, audit = merge_region("demo", [r], tmp_path / "a", tmp_path / "b")
    assert merged[0]["dwelling"]["households"][0]["house"]["washouse"]["value"] == "1"
    assert audit[0]["overrides"]["Washouse"] == "primary_label_alias_recovered"
    assert r["dwelling"]["households"][0]["house"]["washouse"]["status"] == "omitted"


@pytest.mark.parametrize("action", ["accept", "correct", "no_data", "illegible"])
def test_real_review_payload_and_history_survive(tmp_path, action, prepared):
    service, _ = setup_review(tmp_path)
    result = decide(
        service, refs()[1], action=action, value="09" if action == "correct" else None
    )
    original = deepcopy(service.store.regions["demo"][0][0])
    fields = {
        "Municipality": "27",
        "Number of Dwelling": "6",
        "Number of Household": "1",
        "Weekly Rent": "04",
        "Occupation of H.": "4",
        "Age of Head": "50",
        "Garden": "1",
    }
    for page in (1, 2):
        a = ExtractionResult(
            fields={
                **fields,
                "Number of Household": str(page),
                "Weekly Rent": "04" if page == 1 else "12",
            }
        )
        cached(tmp_path / "a", a, page)
        cached(tmp_path / "b", a, page)
    merged, _ = merge_region("demo", [original], tmp_path / "a", tmp_path / "b")
    actual = merged[0]["dwelling"]["households"][1]["coding"]["weekly_rent"]
    assert actual == result["item"]["field"]
    assert merged[0]["dwelling"]["notes"] == original["dwelling"]["notes"]
    assert merged[0]["dwelling"]["address"] == original["dwelling"]["address"]
    assert all(c["confidence"] == 0.0 for c in merged[0]["dwelling"]["cards"])
    validate_records(merged, "demo")


def test_accepted_omitted_field_never_filled(tmp_path, prepared):
    service, _ = setup_review(tmp_path)
    ref = replace(refs()[2], field_path="/dwelling/households/0/house/washouse")
    service.replace_queue([ref], [])
    accepted = decide(service, ref, action="accept", value=None)["item"]["field"]
    a = reading()
    r = single(a)
    r["dwelling"]["households"][0]["house"]["washouse"] = deepcopy(accepted)
    score_household(r, 0, a, a)
    assert r["dwelling"]["households"][0]["house"]["washouse"] == accepted


def test_identity_reread_is_preserved_without_qwen_agreement():
    a = reading()
    r = single(a)
    r["dwelling"]["households"][0]["dwelling_no"]["value"] = "7"
    _, scores, overrides = score_household(r, 0, a, a)
    assert scores["Number of Dwelling"]["value"] == "7"
    assert scores["Number of Dwelling"]["confidence"] == 0.0
    assert scores["Number of Dwelling"]["source_agreement"] == "no_second_opinion"
    assert overrides["Number of Dwelling"] == "gemini_identity_recovery_uncalibrated"


def test_unsupported_form_never_inherits_c1_calibration():
    a = reading()
    r = single(a)
    _, scores, _ = score_household(r, 0, a, a, unsupported_form="C3")
    assert {s["confidence"] for s in scores.values()} == {0.0}
    assert r["dwelling"]["households"][0]["cards"][0]["confidence"] == 0.0


def test_ordinary_agreement_uses_recalibrated_score():
    a = reading()
    r = single(a)
    score_household(r, 0, a, a)
    assert r["dwelling"]["households"][0]["house"]["garden"]["confidence"] == 0.98


def test_unexplained_primary_drift_refuses():
    a = reading()
    r = single(a)
    r["dwelling"]["households"][0]["house"]["garden"]["value"] = "9"
    with pytest.raises(ValueError, match="differs"):
        score_household(r, 0, a, a)


def test_merge_refuses_incompatible_primary_prompt(tmp_path):
    a = reading()
    a.struck = {}
    cached(tmp_path / "a", a)
    cached(tmp_path / "b", a)
    with pytest.raises(ValueError, match="D028"):
        merge_region("demo", [single(a)], tmp_path / "a", tmp_path / "b")


def test_staging_cannot_overwrite_inputs_or_existing_artifacts(tmp_path):
    from survey.merge_runs import merge_dataset

    inputs = [tmp_path / n for n in ("primary", "secondary", "gcache", "qcache")]
    with pytest.raises(ValueError, match="isolated"):
        merge_dataset(*inputs, inputs[0], tmp_path / "excluded.json")
    out = tmp_path / "stage"
    out.mkdir()
    marker = out / "keep.txt"
    marker.write_text("existing")
    with pytest.raises(ValueError, match="new or empty"):
        merge_dataset(*inputs, out, tmp_path / "excluded.json")
    assert marker.read_text() == "existing"


def test_configuration_and_source_discrepancies_fail_before_writing(tmp_path):
    from survey.merge_runs import EXPECTED_QWEN, merge_dataset

    a = reading()
    r = single(a)
    primary, secondary = tmp_path / "primary", tmp_path / "secondary"
    for folder in (primary, secondary):
        folder.mkdir()
        (folder / "demo.jsonl").write_text(json.dumps(r) + "\n")
    excluded = tmp_path / "excluded.json"
    excluded.write_text("[]")
    (secondary / "extractor.json").write_text(
        json.dumps({**EXPECTED_QWEN, "weights": "Q4_K_M"})
    )
    out = tmp_path / "stage"
    with pytest.raises(ValueError, match="configuration"):
        merge_dataset(primary, secondary, tmp_path / "g", tmp_path / "q", out, excluded)
    assert not out.exists()
    (secondary / "extractor.json").write_text(json.dumps(EXPECTED_QWEN))
    r["dwelling"]["households"][0]["cards"][0]["page"] = 2
    (secondary / "demo.jsonl").write_text(json.dumps(r) + "\n")
    with pytest.raises(ValueError, match="unpublished"):
        merge_dataset(primary, secondary, tmp_path / "g", tmp_path / "q", out, excluded)
    excluded.write_text(
        json.dumps([{"region": "demo", "pdf": "synthetic.pdf", "page": 1}])
    )
    with pytest.raises(ValueError, match="excluded"):
        merge_dataset(primary, secondary, tmp_path / "g", tmp_path / "q", out, excluded)
    assert not out.exists()


def prepared_merge(tmp_path, primary_reading=None, secondary_reading=None):
    """A complete isolated merge input, including matching configuration files."""
    from survey.merge_runs import EXPECTED_QWEN, GEMINI, QWEN, QWEN_CACHE

    a = primary_reading if primary_reading is not None else reading()
    b = secondary_reading if secondary_reading is not None else reading()
    primary, secondary = tmp_path / "primary", tmp_path / "secondary"
    for folder, result in ((primary, a), (secondary, b)):
        folder.mkdir()
        (folder / "demo.jsonl").write_text(json.dumps(single(result)) + "\n")
    (secondary / "extractor.json").write_text(json.dumps(EXPECTED_QWEN))
    gcache, qcache = tmp_path / "gcache", tmp_path / "qcache"
    cached(gcache / "demo" / GEMINI, a)
    qfolder = qcache / "demo" / QWEN / QWEN_CACHE
    cached(qfolder, b)
    (qfolder / "extractor.json").write_text(json.dumps(EXPECTED_QWEN))
    excluded = tmp_path / "excluded.json"
    excluded.write_text("[]")
    return primary, secondary, gcache, qcache, tmp_path / "stage", excluded


def test_same_source_reread_refuses_stale_qwen_cache_before_scoring_or_writing(
    tmp_path, monkeypatch
):
    import survey.merge_runs as merge

    # The PDF, region, page and configuration are unchanged. A fresh reading
    # differs from the old cache, which would falsely corroborate Gemini.
    inputs = prepared_merge(tmp_path, secondary_reading=reading(Garden="2"))
    qfolder = inputs[3] / "demo" / merge.QWEN / merge.QWEN_CACHE
    cached(qfolder, reading(Garden="1"))
    published = (inputs[1] / "demo.jsonl").read_bytes()
    old_cache = (qfolder / "synthetic_p0001.json").read_bytes()

    def forbidden(*args, **kwargs):
        pytest.fail("stale secondary evidence must fail before scoring or writing")

    monkeypatch.setattr(merge, "merge_region", forbidden)
    monkeypatch.setattr(merge, "write_atomic", forbidden)
    with pytest.raises(ValueError, match="Published Qwen field differs.*Garden"):
        merge.merge_dataset(*inputs)
    assert not inputs[4].exists()
    assert (inputs[1] / "demo.jsonl").read_bytes() == published
    assert (qfolder / "synthetic_p0001.json").read_bytes() == old_cache


def test_matching_qwen_cache_accepts_known_aliases_and_normalized_values(tmp_path):
    from survey.merge_runs import QWEN, QWEN_CACHE, merge_dataset

    inputs = prepared_merge(tmp_path)
    b = reading(Garden="1.")
    del b.fields["Washouse"]
    b.raw_text = json.dumps({"Washhouse": "1"})
    cached(inputs[3] / "demo" / QWEN / QWEN_CACHE, b)
    summary = merge_dataset(*inputs)
    assert summary[0]["coding_cards"] == 1
    assert summary[0]["classes"] == {"agree": len(FIELD_SCHEMA)}
    assert (inputs[4] / "demo.jsonl").is_file()


@pytest.mark.parametrize("cache_omitted", [True, False])
def test_qwen_cache_omission_and_explicit_blank_are_not_interchangeable(
    tmp_path, cache_omitted
):
    from survey.merge_runs import QWEN, QWEN_CACHE, merge_dataset

    published, raw = reading(Garden=""), reading(Garden="")
    del (raw if cache_omitted else published).fields["Garden"]
    inputs = prepared_merge(tmp_path, secondary_reading=published)
    cached(inputs[3] / "demo" / QWEN / QWEN_CACHE, raw)
    with pytest.raises(ValueError, match="Published Qwen field differs.*Garden"):
        merge_dataset(*inputs)
    assert not inputs[4].exists()


def test_qwen_cache_guard_compares_household_owned_fields_only(tmp_path):
    from survey.merge_runs import (
        EXPECTED_QWEN,
        QWEN,
        QWEN_CACHE,
        validate_secondary_cache,
    )

    first = reading()
    second = reading(**{"Number of Household": "2", "Garden": "2", "Weekly Rent": "12"})
    record = single(first)
    household = single(second)["dwelling"]["households"][0]
    household["cards"][0]["page"] = 2
    record["dwelling"]["households"].append(household)
    folder = tmp_path / "demo" / QWEN / QWEN_CACHE
    cached(folder, first)
    cached(folder, second, page=2)
    (folder / "extractor.json").write_text(json.dumps(EXPECTED_QWEN))
    dataset = {"demo": ([record], "unused digest")}
    snapshot = deepcopy(record)
    # The shared Garden is held only by the first household's envelope. The
    # second household's distinct raw Garden cannot be validated against it.
    validate_secondary_cache(dataset, tmp_path, EXPECTED_QWEN)
    assert record == snapshot
    cached(folder, reading(**{**second.fields, "Weekly Rent": "9"}), page=2)
    with pytest.raises(ValueError, match="Published Qwen field differs.*Weekly Rent"):
        validate_secondary_cache(dataset, tmp_path, EXPECTED_QWEN)
    assert record == snapshot


def test_qwen_cache_guard_reads_a_0_6_export(tmp_path):
    from survey.merge_runs import (
        EXPECTED_QWEN,
        QWEN,
        QWEN_CACHE,
        coding_targets,
        validate_secondary_cache,
    )

    first = reading()
    second = reading(**{"Number of Household": "2", "Garden": "2"})
    record = single(first)
    household = single(second)["dwelling"]["households"][0]
    household["cards"][0]["page"] = 2
    record["dwelling"]["households"].append(household)
    record = review_support.legacy(record)
    d = record["dwelling"]
    # 0.6.0: the shared fields are the first card's alone.
    assert dict(coding_targets(record, 0))["Garden"] is d["house"]["garden"]
    later = dict(coding_targets(record, 1))
    assert "Garden" not in later
    assert later["Municipality"] is d["households"][1]["municipality"]
    folder = tmp_path / "demo" / QWEN / QWEN_CACHE
    cached(folder, first)
    cached(folder, second, page=2)
    (folder / "extractor.json").write_text(json.dumps(EXPECTED_QWEN))
    validate_secondary_cache({"demo": ([record], "unused")}, tmp_path, EXPECTED_QWEN)


def test_reviewed_qwen_discrepancy_refuses_without_overwriting_human_decision(tmp_path):
    from survey.merge_runs import merge_dataset

    inputs = prepared_merge(tmp_path)
    path = inputs[1] / "demo.jsonl"
    record = json.loads(path.read_text())
    field = record["dwelling"]["households"][0]["house"]["garden"]
    # A human-modified published value is not proof of the supplied raw
    # reading's lineage; preserve it and require matching evidence.
    field.update(value="2", origin="corrected", original_value="1")
    path.write_text(json.dumps(record) + "\n")
    original = path.read_bytes()
    with pytest.raises(
        ValueError, match="reviewed field; matching raw evidence required"
    ):
        merge_dataset(*inputs)
    assert path.read_bytes() == original
    assert not inputs[4].exists()

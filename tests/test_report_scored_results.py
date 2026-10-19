"""Candidate reporting must follow its inputs, not a historical run narrative."""

import importlib.util
import json
from collections import Counter
from pathlib import Path

import pytest

from survey.extraction.card_fields import FIELD_SCHEMA
from survey.extraction.record import build_record
from survey.records import current_fields, digest

MODULE = Path(__file__).parents[1] / "scripts/report_scored_results.py"
spec = importlib.util.spec_from_file_location("report_scored_results", MODULE)
reporter = importlib.util.module_from_spec(spec)
spec.loader.exec_module(reporter)


def write_json(path, value):
    path.write_text(json.dumps(value))


def write_jsonl(path, rows):
    path.write_text("".join(json.dumps(row) + "\n" for row in rows))


def candidate(
    tmp_path, *, records=1, protected_first=False, excluded=2, date="2030-03-04"
):
    """Small self-contained candidate; no external corpus/validation claims."""
    directory = tmp_path / "candidate"
    directory.mkdir()
    (directory / "pairing").mkdir()
    data, audit = [], []
    for index in range(records):
        fields = {spec.name: "1" for spec in FIELD_SCHEMA}
        fields.update(
            {
                "Municipality": "27",
                "Number of Dwelling": str(index + 1),
                "Number of Household": "1",
            }
        )
        record = build_record(
            fields, region="demo", image="case.pdf", page=index + 1, struck=None
        )
        for _, field in current_fields(record):
            field["confidence"] = 0.64
        garden = record["dwelling"]["house"]["garden"]
        garden["confidence"] = 0.98
        if index == 0 and protected_first:
            garden["origin"] = "corrected"
        record["supplementary_notes"] = {
            "value": "source wording",
            "status": "ok",
            "source": "survey-front",
            "confidence": None,
        }
        record["dwelling"]["households"][0]["cards"][0]["confidence"] = 0.64
        record["dwelling"]["cards"] = [
            {
                "role": "survey-front",
                "image": "case.pdf",
                "page": index + 101,
                "confidence": 0.0,
            }
        ]
        data.append(record)
        audit.append(
            {
                "region": "demo",
                "pdf": "case.pdf",
                "page": index + 1,
                "secondary_state": "available",
                "fields": {
                    spec.name: {
                        "agreement": "agree" if spec.name == "Garden" else "disagree",
                        "source_agreement": "agree"
                        if spec.name == "Garden"
                        else "disagree",
                    }
                    for spec in FIELD_SCHEMA
                },
                "overrides": {
                    "Garden": "human_review_preserved"
                    if index == 0 and protected_first
                    else "primary_label_alias_recovered"
                },
            }
        )
    write_jsonl(directory / "demo.jsonl", data)
    write_jsonl(directory / "pairing/demo.jsonl", audit)
    classes = dict(
        Counter({"agree": records, "disagree": (len(FIELD_SCHEMA) - 1) * records})
    )
    write_json(
        directory / "summary.json",
        [
            {
                "region": "demo",
                "dwellings": records,
                "coding_cards": records,
                "comparison_fields": len(FIELD_SCHEMA) * records,
                "raw_classes": classes,
                "classes": classes,
                "exported_fields": (len(FIELD_SCHEMA) + 2) * records,
                "numeric_field_scores": (len(FIELD_SCHEMA) + 1) * records,
                "protected_fields": int(protected_first),
                "skip_review_fields": records - int(protected_first),
                "mean_numeric_field_confidence": (0.98 + 0.64 * len(FIELD_SCHEMA))
                / (len(FIELD_SCHEMA) + 1),
                "null_ids": records,
                "flags": {"unplaced": records},
            }
        ],
    )
    sample = tmp_path / "sample.json"
    write_json(
        sample,
        {
            "C3": [
                {
                    "region": "demo",
                    "pdf": "case.pdf",
                    "page": 1,
                    "gemini_published_roles": [],
                }
            ],
            "S3": [
                {
                    "region": "demo",
                    "pdf": "case.pdf",
                    "page": 101,
                    "gemini_published_roles": [],
                }
            ],
            "R1": [
                {
                    "region": "demo",
                    "pdf": "case.pdf",
                    "page": 999,
                    "gemini_published_roles": ["stale published association"],
                }
            ],
        },
    )
    write_json(
        directory / "merge-manifest.json",
        {
            "date": date,
            "primary": "fixture-primary",
            "secondary": {"weights": "fixture-Q6"},
            "primary_files": {"demo.jsonl": "input-primary-hash"},
            "secondary_files": {"demo.jsonl": "input-secondary-hash"},
            "excluded_sources": excluded,
            "excluded_sha256": "fixture-exclusion-hash",
            "secondary_type_evidence_sha256": digest(sample.read_bytes()),
            "policy": "fixture candidate policy",
            "paths": {
                "primary": "fixture/new-primary",
                "secondary": "fixture/new-secondary",
            },
            "empty_regions": {"empty-region": "front-only material"},
            "region_inventory": ["demo", "empty-region"],
        },
    )
    return directory, sample


def test_counts_dates_paths_and_provenance_follow_candidate(tmp_path):
    directory, sample = candidate(
        tmp_path, records=3, protected_first=True, excluded=9, date="2031-06-07"
    )
    result = reporter.report(directory, secondary_evidence=sample)
    assert result["dwellings"] == result["coding_cards"] == 3
    assert result["comparison_fields"] == 3 * len(FIELD_SCHEMA)
    assert result["exported_fields"] == 3 * (len(FIELD_SCHEMA) + 2)
    assert result["protected_fields"] == 1
    assert result["overrides"] == {
        "human_review_preserved": 1,
        "primary_label_alias_recovered": 2,
    }
    assert result["skip_review_fields"] == 2
    assert result["skip_review_share_exported"] == 2 / result["exported_fields"]
    assert result["report_date"] == "2031-06-07"
    assert result["excluded_sources"] == 9
    assert result["regions_accounted"] == 2
    assert result["paths"]["candidate"] == str(directory.resolve())
    assert result["paths"]["primary"] == "fixture/new-primary"
    assert result["provenance"]["manifest"]["secondary"] == {"weights": "fixture-Q6"}
    assert result["provenance"]["dataset_files"]["demo.jsonl"] == digest(
        (directory / "demo.jsonl").read_bytes()
    )
    text = reporter.markdown(result)
    assert "2031-06-07" in text
    assert f"| demo | 3 | 3 | 3/{result['comparison_fields']} |" in text
    assert f"2/{result['exported_fields']}" in text
    assert "fixture candidate policy" in text
    assert "fixture/new-primary" in text
    assert "**9**" in text
    for outdated in (
        "17 October 2026",
        "775 tests",
        "13 legacy",
        "data/it125-repeat",
        "5,356",
        "All 216 excluded",
    ):
        assert outdated not in text
    assert result["acceptance"]["AC1"]["coding_confidence_complete"] is True
    assert result["acceptance"]["AC2"]["all_stored_cards_numerically_scored"] is True


def test_changed_manifest_is_not_replaced_by_historical_defaults(tmp_path):
    directory, sample = candidate(tmp_path)
    manifest_path = directory / "merge-manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest.update(date="2033-08-09", excluded_sources=17, policy="revised policy")
    manifest.pop("region_inventory")
    manifest.pop("empty_regions")
    write_json(manifest_path, manifest)
    result = reporter.report(directory, secondary_evidence=sample)
    assert result["report_date"] == "2033-08-09"
    assert result["excluded_sources"] == 17
    assert result["regions_accounted"] == 1
    assert result["empty_regions"] == {}
    assert result["region_inventory_complete"] is False
    assert "revised policy" in reporter.markdown(result)
    assert result["provenance"]["manifest_sha256"] == digest(manifest_path.read_bytes())


def test_sample_intersections_use_candidate_sources_not_old_published_roles(tmp_path):
    directory, sample = candidate(tmp_path)
    result = reporter.report(directory, secondary_evidence=sample)
    assert result["known_secondary_sample"] == {
        "C3": {"identified": 1, "published_sources": 1, "published_coding_sources": 1},
        "S3": {"identified": 1, "published_sources": 1, "published_coding_sources": 0},
        "R1": {"identified": 1, "published_sources": 0, "published_coding_sources": 0},
    }
    assert result["full_corpus_secondary_census"] is None
    assert result["acceptance"]["AC3"]["full_census_required"] is False
    text = reporter.markdown(result)
    assert "not an acceptance blocker" in text
    assert "accepted as-is as supplementary" in text
    assert "IT-109/IT-115" in text
    assert "Unsupported secondary forms are ignored" in text


def test_generator_does_not_invent_tests_publication_or_preservation_passes(tmp_path):
    directory, sample = candidate(tmp_path)
    result = reporter.report(directory, secondary_evidence=sample)
    text = reporter.markdown(result)
    assert result["verification_evidence"] == {}
    assert result["lost_published_coding_sources"] is None
    assert result["local_merge_runtime"] is None
    assert "No external verification evidence was supplied" in text
    assert (
        "does not establish that this candidate is the current published dataset"
        in text
    )
    assert "passed **" not in text
    assert "byte-identical" not in text
    assert "unchanged human payloads" in text


def test_supplied_evidence_runtime_and_date_are_attributed_without_rerunning_checks(
    tmp_path,
):
    directory, sample = candidate(tmp_path)
    evidence = {
        "tests": {"status": "passed", "passed": 123, "evidence": "fixture-tests.log"},
        "publication": {"status": "not-run", "path": "fixture-target"},
    }
    runtime = {"elapsed_seconds": 4.25, "scope": "fixture measurement"}
    result = reporter.report(
        directory,
        runtime,
        evidence=evidence,
        report_date="2034-10-11",
        secondary_evidence=sample,
    )
    assert result["verification_evidence"] == evidence
    assert result["local_merge_runtime"] == runtime
    assert result["report_date"] == "2034-10-11"
    text = reporter.markdown(result)
    assert '"passed": 123' in text
    assert '"elapsed_seconds": 4.25' in text
    assert "not rerun by this report" in text
    assert "fixture-target" in text


def test_incomplete_or_stale_candidate_artifacts_are_refused(tmp_path):
    directory, sample = candidate(tmp_path)
    audit_path = directory / "pairing/demo.jsonl"
    audit_path.unlink()
    with pytest.raises(ValueError, match="pairing region files"):
        reporter.report(directory, secondary_evidence=sample)


def test_candidate_summary_count_drift_is_refused(tmp_path):
    directory, sample = candidate(tmp_path)
    summary_path = directory / "summary.json"
    summary = json.loads(summary_path.read_text())
    summary[0]["numeric_field_scores"] += 1
    write_json(summary_path, summary)
    with pytest.raises(ValueError, match="numeric_field_scores mismatch"):
        reporter.report(directory, secondary_evidence=sample)


def test_pending_refresh_manifest_is_not_a_completed_candidate(tmp_path):
    directory, sample = candidate(tmp_path)
    manifest_path = directory / "merge-manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["current_refresh_status"] = {"fresh_qwen_raw_handoff_required": True}
    write_json(manifest_path, manifest)
    with pytest.raises(ValueError, match="incomplete refresh"):
        reporter.report(directory, secondary_evidence=sample)


def test_mismatched_secondary_evidence_hash_is_refused(tmp_path):
    directory, sample = candidate(tmp_path)
    sample.write_text("{}")
    with pytest.raises(ValueError, match="manifest hash"):
        reporter.report(directory, secondary_evidence=sample)


def test_missing_optional_sample_is_unknown_not_fabricated_or_full_census_blocker(
    tmp_path, monkeypatch
):
    directory, _ = candidate(tmp_path)
    monkeypatch.setattr(reporter, "SECONDARY_EVIDENCE", tmp_path / "not-supplied.json")
    result = reporter.report(directory)
    assert result["known_secondary_sample"] == {}
    assert result["acceptance"]["AC3"]["known_secondary_counts_reported"] is False
    assert result["acceptance"]["AC3"]["full_census_required"] is False
    assert "sample counts remain unreported" in reporter.markdown(result)


def test_unscored_card_is_reported_without_claiming_ac2_met(tmp_path):
    directory, sample = candidate(tmp_path)
    path = directory / "demo.jsonl"
    records = [json.loads(line) for line in path.read_text().splitlines()]
    records[0]["dwelling"]["cards"][0]["confidence"] = None
    write_jsonl(path, records)
    result = reporter.report(directory, secondary_evidence=sample)
    assert result["unscored_or_invalid_cards"] == 1
    assert result["acceptance"]["AC2"]["all_stored_cards_numerically_scored"] is False


def test_existing_cli_and_new_optional_evidence_write_only_requested_report(
    tmp_path, monkeypatch
):
    directory, sample = candidate(tmp_path)
    evidence_path = tmp_path / "evidence.json"
    write_json(evidence_path, {"schema": {"status": "not-supplied"}})
    output = tmp_path / "report" / "candidate-summary"
    before = {str(p): p.read_bytes() for p in directory.rglob("*") if p.is_file()}
    monkeypatch.setattr(
        "sys.argv",
        [
            str(MODULE),
            "--dataset",
            str(directory),
            "--output",
            str(output),
            "--secondary-evidence",
            str(sample),
            "--evidence",
            str(evidence_path),
            "--report-date",
            "2035-01-02",
        ],
    )
    reporter.main()
    report = json.loads(output.with_suffix(".json").read_text())
    assert report["report_date"] == "2035-01-02"
    assert output.with_suffix(".md").is_file()
    assert {
        str(p): p.read_bytes() for p in directory.rglob("*") if p.is_file()
    } == before


def test_unlabelled_coding_null_is_counted_in_confidence_completeness(tmp_path):
    directory, sample = candidate(tmp_path)
    path = directory / "demo.jsonl"
    records = [json.loads(line) for line in path.read_text().splitlines()]
    field = records[0]["dwelling"]["house"]["washouse"]
    assert "source" not in field
    field["confidence"] = None
    write_jsonl(path, records)
    summary_path = directory / "summary.json"
    summary = json.loads(summary_path.read_text())
    summary[0]["numeric_field_scores"] -= 1
    summary[0]["mean_numeric_field_confidence"] = (
        0.98 + 0.64 * (len(FIELD_SCHEMA) - 1)
    ) / len(FIELD_SCHEMA)
    write_json(summary_path, summary)
    result = reporter.report(directory, secondary_evidence=sample)
    assert result["coding_field_leaves"] == len(FIELD_SCHEMA) + 1
    assert result["numeric_coding_field_leaves"] == len(FIELD_SCHEMA)
    assert result["acceptance"]["AC1"]["coding_confidence_complete"] is False


@pytest.mark.parametrize(
    "field,value", [("skip_review_fields", 0), ("mean_numeric_field_confidence", 0.99)]
)
def test_summary_cannot_override_observed_skip_or_mean(tmp_path, field, value):
    directory, sample = candidate(tmp_path)
    summary_path = directory / "summary.json"
    summary = json.loads(summary_path.read_text())
    summary[0][field] = value
    write_json(summary_path, summary)
    with pytest.raises(
        ValueError, match="skip_review_fields mismatch|mean confidence differs"
    ):
        reporter.report(directory, secondary_evidence=sample)


def test_verification_evidence_binding_rejects_a_different_candidate(tmp_path):
    directory, sample = candidate(tmp_path)
    manifest_hash = digest((directory / "merge-manifest.json").read_bytes())
    evidence = {
        "candidate_manifest_sha256": manifest_hash,
        "schema": {"status": "supplied-check"},
    }
    result = reporter.report(directory, evidence=evidence, secondary_evidence=sample)
    assert result["verification_evidence"] == evidence
    with pytest.raises(ValueError, match="different candidate manifest"):
        reporter.report(
            directory,
            evidence={**evidence, "candidate_manifest_sha256": "stale-hash"},
            secondary_evidence=sample,
        )

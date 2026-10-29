"""Report one completed isolated merge candidate; never infer publication.

Optional --evidence accepts a JSON object of named verification checks, for
example {"schema": {"status": "passed", "evidence": "data/schema.log"}}.
Evidence is attributed to its supplier; generating a report does not run those
checks. --runtime retains the existing measured-runtime JSON interface.
"""

import argparse
import json
from collections import Counter
from datetime import date as calendar_date
from datetime import datetime
from math import isclose
from pathlib import Path
from zoneinfo import ZoneInfo

from survey.merge_runs import SECONDARY_EVIDENCE, coding_targets, protected
from survey.records import current_fields, digest
from survey.review.routing import needs_review


def _ratio(numerator, denominator):
    return numerator / denominator if denominator else None


def _numeric(score):
    return (
        isinstance(score, (int, float))
        and not isinstance(score, bool)
        and 0 <= score <= 1
    )


def _cards(node):
    if isinstance(node, dict):
        if "role" in node and "image" in node:
            yield node
        else:
            for key, value in node.items():
                if key != "review":
                    yield from _cards(value)
    elif isinstance(node, list):
        for value in node:
            yield from _cards(value)


def _jsonl(path):
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _check_equal(label, actual, expected):
    if actual != expected:
        raise ValueError(
            f"Candidate {label} mismatch: observed {actual!r}, summary {expected!r}"
        )


def report(
    directory, runtime=None, *, evidence=None, report_date=None, secondary_evidence=None
):
    """Derive a snapshot from this candidate's data, summary, audit and manifest.

    Refuse incomplete/mismatched artifacts instead of combining stale summaries
    with a new export. Validation/acceptance observations below concern only
    what this generator actually measures; supplied external checks are separate.
    """
    directory = Path(directory)
    manifest_path, summary_path = (
        directory / "merge-manifest.json",
        directory / "summary.json",
    )
    manifest = json.loads(manifest_path.read_text())
    rows = json.loads(summary_path.read_text())
    evidence = {} if evidence is None else evidence
    if not isinstance(evidence, dict):
        raise TypeError("Verification evidence must be a JSON object of named checks")
    bound_hash = evidence.get("candidate_manifest_sha256")
    if bound_hash is not None and bound_hash != digest(manifest_path.read_bytes()):
        raise ValueError(
            "Verification evidence is bound to a different candidate manifest"
        )
    if manifest.get("current_refresh_status", {}).get(
        "fresh_qwen_raw_handoff_required"
    ):
        raise ValueError(
            "Candidate manifest describes an incomplete refresh awaiting Qwen raw inputs"
        )
    region_rows = {row["region"]: row for row in rows}
    if len(region_rows) != len(rows):
        raise ValueError("Candidate summary contains duplicate regions")
    files = {path.stem: path for path in sorted(directory.glob("*.jsonl"))}
    _check_equal("region files", set(files), set(region_rows))
    for key in ("primary_files", "secondary_files"):
        if key in manifest:
            named = {Path(name).stem for name in manifest[key]}
            # A wholly missing secondary region is only permissible when the
            # manifest explicitly records that its sources had no second arm.
            if key == "primary_files":
                _check_equal("primary manifest regions", set(files), named)
            elif not named <= set(files):
                raise ValueError(
                    "Secondary manifest names unpublished candidate regions"
                )
    pairing_files = {
        path.stem: path for path in sorted((directory / "pairing").glob("*.jsonl"))
    }
    _check_equal("pairing region files", set(pairing_files), set(files))
    audit_rows, source_cards, role_counts, card_scores = [], {}, Counter(), []
    null_fields, invalid_fields = Counter(), 0
    exported = numeric = protected_count = coding_fields = scored_coding_fields = 0
    skip = 0
    score_sum = 0.0
    for region, path in files.items():
        records, audit = _jsonl(path), _jsonl(pairing_files[region])
        row = region_rows[region]
        _check_equal(f"{region} dwellings", len(records), row["dwellings"])
        _check_equal(f"{region} coding cards", len(audit), row["coding_cards"])
        region_sources = set()
        region_exported = region_numeric = region_protected = region_skip = 0
        region_score_sum = 0.0
        for record in records:
            # Most coding fields deliberately have no source attribute. Follow
            # actual envelope ownership: every household owns its own fields.
            owned_coding_fields = {
                id(field)
                for index, _ in enumerate(record["dwelling"]["households"])
                for _, field in coding_targets(record, index)
            }
            for card in _cards(record):
                role_counts[card["role"]] += 1
                card_scores.append(card.get("confidence"))
                source = (region, card["image"], card["page"])
                source_cards.setdefault(source, set()).add(card["role"])
                if card["role"] == "coding-front":
                    if source in region_sources:
                        raise ValueError(f"Duplicate candidate coding source: {source}")
                    region_sources.add(source)
            for _, field in current_fields(record):
                region_exported += 1
                score = field.get("confidence")
                numeric_score = _numeric(score)
                region_numeric += numeric_score
                invalid_fields += score is not None and not numeric_score
                region_protected += bool(protected(field))
                region_skip += (
                    not protected(field) and numeric_score and not needs_review(field)
                )
                if numeric_score:
                    region_score_sum += score
                if id(field) in owned_coding_fields:
                    coding_fields += 1
                    scored_coding_fields += _numeric(score)
                if score is None:
                    null_fields[field.get("source", "unspecified")] += 1
        for name, actual in (
            ("exported_fields", region_exported),
            ("numeric_field_scores", region_numeric),
            ("protected_fields", region_protected),
            ("skip_review_fields", region_skip),
        ):
            _check_equal(f"{region} {name}", actual, row[name])
        actual_mean = _ratio(region_score_sum, region_numeric)
        declared_mean = row["mean_numeric_field_confidence"]
        if actual_mean is None:
            _check_equal(f"{region} mean confidence", declared_mean, None)
        elif declared_mean is None or not isclose(
            actual_mean, declared_mean, rel_tol=1e-12, abs_tol=1e-12
        ):
            raise ValueError(
                f"Candidate {region} mean confidence differs from stored field scores"
            )
        audit_sources = [(r["region"], r["pdf"], r["page"]) for r in audit]
        if len(audit_sources) != len(set(audit_sources)):
            raise ValueError(f"Duplicate pairing source in {region}")
        _check_equal(
            f"{region} pairing source coverage", set(audit_sources), region_sources
        )
        raw = Counter(f["agreement"] for item in audit for f in item["fields"].values())
        effective = Counter(
            f["source_agreement"] for item in audit for f in item["fields"].values()
        )
        _check_equal(f"{region} raw classes", raw, Counter(row["raw_classes"]))
        _check_equal(f"{region} scored classes", effective, Counter(row["classes"]))
        _check_equal(
            f"{region} comparison fields",
            sum(effective.values()),
            row["comparison_fields"],
        )
        exported += region_exported
        numeric += region_numeric
        protected_count += region_protected
        skip += region_skip
        score_sum += region_score_sum
        audit_rows.extend(audit)
    effective = sum((Counter(r["classes"]) for r in rows), Counter())
    raw = sum((Counter(r["raw_classes"]) for r in rows), Counter())
    overrides = Counter(
        reason for r in audit_rows for reason in r.get("overrides", {}).values()
    )
    known_sample, sample_provenance = {}, None
    sample_path = Path(secondary_evidence) if secondary_evidence else SECONDARY_EVIDENCE
    expected_sample_hash = manifest.get("secondary_type_evidence_sha256")
    if sample_path.is_file() and expected_sample_hash:
        content = sample_path.read_bytes()
        if digest(content) != expected_sample_hash:
            raise ValueError(
                "Secondary-form evidence does not match the candidate manifest hash"
            )
        secondary = json.loads(content)
        known_sample = {
            form: {
                "identified": len(sources),
                "published_sources": sum(
                    (s["region"], s["pdf"], s["page"]) in source_cards for s in sources
                ),
                "published_coding_sources": sum(
                    "coding-front"
                    in source_cards.get((s["region"], s["pdf"], s["page"]), set())
                    for s in sources
                ),
            }
            for form, sources in secondary.items()
        }
        sample_provenance = {
            "path": str(sample_path.resolve()),
            "sha256": digest(content),
        }
    elif secondary_evidence:
        raise ValueError(
            "Explicit secondary-form evidence requires a file and its candidate manifest hash"
        )
    empty_regions = manifest.get("empty_regions", {})
    named_regions = set(region_rows) | set(empty_regions)
    inventory = manifest.get("region_inventory")
    if inventory is not None:
        named_regions |= set(inventory)
    valid_card_scores = [score for score in card_scores if _numeric(score)]
    date = report_date or manifest.get("created_at") or manifest.get("date")
    date = (
        str(date)[:10]
        if date
        else datetime.now(ZoneInfo("Australia/Melbourne")).date().isoformat()
    )
    coding_complete = coding_fields == scored_coding_fields and invalid_fields == 0
    cards_complete = len(valid_card_scores) == len(card_scores)
    return {
        "report_date": date,
        "candidate_created_at": manifest.get("created_at", manifest.get("date")),
        "candidate_directory": str(directory.resolve()),
        "provenance": {
            "manifest": manifest,
            "manifest_path": str(manifest_path.resolve()),
            "manifest_sha256": digest(manifest_path.read_bytes()),
            "summary_sha256": digest(summary_path.read_bytes()),
            "dataset_files": {p.name: digest(p.read_bytes()) for p in files.values()},
            "pairing_files": {
                p.name: digest(p.read_bytes()) for p in pairing_files.values()
            },
            "secondary_sample": sample_provenance,
        },
        "paths": {"candidate": str(directory.resolve()), **manifest.get("paths", {})},
        "dwellings": sum(r["dwellings"] for r in rows),
        "coding_cards": sum(r["coding_cards"] for r in rows),
        "regions_accounted": len(named_regions),
        "nonempty_regions": sum(r["dwellings"] > 0 for r in rows),
        "empty_regions": empty_regions,
        "region_inventory_complete": inventory is not None,
        "comparison_fields": sum(effective.values()),
        "raw_classes": dict(raw),
        "effective_classes": dict(effective),
        "raw_agreement_share_all": _ratio(raw["agree"], sum(raw.values())),
        "raw_agreement_both_coded": _ratio(
            raw["agree"], raw["agree"] + raw["disagree"]
        ),
        "exported_fields": exported,
        "numeric_field_scores": numeric,
        "null_field_scores": dict(null_fields),
        "invalid_field_scores": invalid_fields,
        "coding_field_leaves": coding_fields,
        "numeric_coding_field_leaves": scored_coding_fields,
        "skip_review_fields": skip,
        "skip_review_share_exported": _ratio(skip, exported),
        "skip_review_share_coding": _ratio(skip, numeric),
        "mean_numeric_field_confidence": _ratio(score_sum, numeric),
        "mean_card_confidence": _ratio(sum(valid_card_scores), len(valid_card_scores)),
        "card_counts": dict(role_counts),
        "unscored_or_invalid_cards": len(card_scores) - len(valid_card_scores),
        "protected_fields": protected_count,
        "overrides": dict(overrides),
        "excluded_sources": manifest.get("excluded_sources"),
        "missing_secondary": [
            {
                "region": r["region"],
                "pdf": r["pdf"],
                "page": r["page"],
                "state": r["secondary_state"],
            }
            for r in audit_rows
            if r["secondary_state"] != "available"
        ],
        "known_secondary_sample": known_sample,
        "full_corpus_secondary_census": None,
        "local_merge_runtime": runtime,
        "lost_published_coding_sources": None,
        "true_missed_or_unclassified_archive_cards": None,
        "null_household_ids": sum(r["null_ids"] for r in rows),
        "dwelling_flags": dict(sum((Counter(r["flags"]) for r in rows), Counter())),
        "regions": rows,
        "verification_evidence": evidence,
        "acceptance": {
            "AC1": {
                "coding_confidence_complete": coding_complete,
                "schema_and_preservation": "see supplied verification evidence; not inferred from report generation",
            },
            "AC2": {"all_stored_cards_numerically_scored": cards_complete},
            "AC3": {
                "regional_agreement_and_review_share_reported": True,
                "known_secondary_counts_reported": bool(sample_provenance),
                "full_census_required": False,
            },
        },
        "scope": {
            "secondary_forms": "Unsupported secondary forms are ignored for the scored extraction scope; any retained placeholders do not gain C1/C2 validation.",
            "secondary_counts": "Known C3/S3/R1 sample counts are reported honestly; unknown full-corpus prevalence is not an acceptance blocker under the clarified scope.",
            "handwriting": "Handwriting, notes and person text are accepted as-is as supplementary information; no accuracy is inferred from their retention.",
            "review_queue": "Queue implementation belongs to IT-109/IT-115 and is outside IT-125; reported skip shares describe eligibility under the candidate policy.",
        },
    }


def _percent(value):
    return "unknown" if value is None else f"{value:.2%}"


def _number(value, precision=4):
    return "unknown" if value is None else f"{value:.{precision}f}"


def markdown(r):
    lines = [
        f"# IT-125 candidate merge report — {r['report_date']}",
        "",
        f"This report describes candidate `{r['candidate_directory']}`: **{r['dwellings']:,} dwellings / {r['coding_cards']:,} physical coding cards**, with {r['nonempty_regions']} nonempty regions. It does not establish that this candidate is the current published dataset.",
        "",
        f"Candidate creation date: {r['candidate_created_at'] or 'not recorded in the manifest'}. Region names accounted for in the supplied artifacts: {r['regions_accounted']}; full project region inventory {'supplied' if r['region_inventory_complete'] else 'not supplied'}. Empty-region declarations: `{json.dumps(r['empty_regions'], sort_keys=True)}`.",
        "",
        "## Agreement and review eligibility",
        "",
        f"Raw normalized agreement: **{r['raw_classes'].get('agree', 0):,}/{r['comparison_fields']:,} = {_percent(r['raw_agreement_share_all'])}** across expected comparison fields; **{_percent(r['raw_agreement_both_coded'])}** where both arms read a nonblank value. Raw and effective class counts remain separate where evidence is uncalibrated or protected.",
        "",
        f"Candidate policy: `{r['provenance']['manifest'].get('policy', 'not recorded')}`. Review-eligible bypass share: **{r['skip_review_fields']:,}/{r['exported_fields']:,} = {_percent(r['skip_review_share_exported'])}** of stored field leaves; {_percent(r['skip_review_share_coding'])} of numeric leaves. These are policy eligibility counts, not a guarantee that the eventual review queue bypasses those fields. Identity flags can still require review; protected human-reviewed fields are excluded from automatic eligibility.",
        "",
        "Confidence summarizes the calibrated evidence for the selected reading. Agreement is not a corpus accuracy guarantee. Blank, omitted, absent and failed readings must remain distinct; Gemini stays primary, including an individual blank or omission. Qwen supplies a value only when the entire primary arm is unavailable.",
        "",
        "## Scores, preservation and discrepancies",
        "",
        "D018 aggregates each coding card's own paired fields with the weakest-quarter mean. Uncalibrated fronts and backs use card score 0 as a no-evidence marker; supplementary handwriting/person/note field confidences may remain null. Neither marker measures handwriting accuracy.",
        "",
        f"Stored fields: {r['exported_fields']:,}; numeric scores: {r['numeric_field_scores']:,}; null scores: {sum(r['null_field_scores'].values()):,}; invalid scores: {r['invalid_field_scores']:,}. Coding-source leaves with numeric scores: {r['numeric_coding_field_leaves']:,}/{r['coding_field_leaves']:,}. Mean numeric field score: {_number(r['mean_numeric_field_confidence'])}.",
        "",
        f"Stored cards: {sum(r['card_counts'].values()):,}, by role `{json.dumps(r['card_counts'], sort_keys=True)}`; unscored/invalid cards: {r['unscored_or_invalid_cards']:,}. Mean numeric card score: {_number(r['mean_card_confidence'])}. These are score summaries, not measured corpus accuracies.",
        "",
        f"Protected field leaves present: **{r['protected_fields']:,}**. Audit override counts: `{json.dumps(r['overrides'], sort_keys=True)}`. Null household identities: {r['null_household_ids']:,}; grouping/identity flags: `{json.dumps(r['dwelling_flags'], sort_keys=True)}`. Presence and counts do not independently establish unchanged human payloads; preservation checks belong in the supplied verification evidence.",
        "",
        f"Excluded-source count declared by this candidate manifest: **{r['excluded_sources'] if r['excluded_sources'] is not None else 'unknown'}**. Missing/failed secondary arms in this candidate: `{json.dumps(r['missing_secondary'], sort_keys=True)}`. The report does not infer zero lost or unclassified archive cards from these observations.",
        "",
        "## Clarified scope and secondary counts",
        "",
        *[
            r["scope"][key]
            for key in (
                "secondary_forms",
                "secondary_counts",
                "handwriting",
                "review_queue",
            )
        ],
        "",
        "| Form | Identified in supplied sample | Present in candidate | Present as coding source |",
        "| --- | ---: | ---: | ---: |",
    ]
    for form, counts in sorted(r["known_secondary_sample"].items()):
        lines.append(
            f"| {form} | {counts['identified']} | {counts['published_sources']} | {counts['published_coding_sources']} |"
        )
    if not r["known_secondary_sample"]:
        lines += [
            "",
            "No hash-matched secondary sample evidence was supplied; sample counts remain unreported.",
        ]
    lines += [
        "",
        "## Per-region figures",
        "",
        "| Region | Dwellings | Coding cards | Raw agree / fields | Raw agree % | Effective agree % | Skip fields / stored | Skip % |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in r["regions"]:
        fields = row["comparison_fields"]
        lines.append(
            f"| {row['region']} | {row['dwellings']} | {row['coding_cards']} | "
            f"{row['raw_classes'].get('agree', 0)}/{fields} | "
            f"{_percent(_ratio(row['raw_classes'].get('agree', 0), fields))} | "
            f"{_percent(_ratio(row['classes'].get('agree', 0), fields))} | "
            f"{row['skip_review_fields']}/{row['exported_fields']} | "
            f"{_percent(_ratio(row['skip_review_fields'], row['exported_fields']))} |"
        )
    for region in sorted(
        set(r["empty_regions"]) - {row["region"] for row in r["regions"]}
    ):
        lines.append(f"| {region} | 0 | 0 | 0/0 | unknown | unknown | 0/0 | unknown |")
    lines += ["", "## Acceptance observations", ""]
    for criterion, observation in r["acceptance"].items():
        lines.append(f"- **{criterion}:** `{json.dumps(observation, sort_keys=True)}`")
    lines += [
        "",
        "These observations establish only the counts/completeness checked by this generator. Acceptance and publication require the relevant candidate-specific verification evidence; generating this report does not run the test suite, schema validator, independent review or determinism checks.",
        "",
        "## Provenance and supplied verification",
        "",
        f"Manifest `{r['provenance']['manifest_path']}` SHA-256 `{r['provenance']['manifest_sha256']}`; summary SHA-256 `{r['provenance']['summary_sha256']}`. Candidate paths: `{json.dumps(r['paths'], sort_keys=True)}`. Input/configuration, exclusion/calibration hashes and candidate file hashes are retained in the JSON report's provenance object.",
        "",
    ]
    if r["local_merge_runtime"] is not None:
        lines += [
            "Supplied merge-runtime evidence:",
            "",
            "```json",
            json.dumps(r["local_merge_runtime"], indent=2, sort_keys=True),
            "```",
            "",
        ]
    else:
        lines += ["Merge runtime was not supplied.", ""]
    if r["verification_evidence"]:
        lines += [
            "Supplied verification evidence (attributed to the supplying checks; not rerun by this report):",
            "",
            "```json",
            json.dumps(r["verification_evidence"], indent=2, sort_keys=True),
            "```",
            "",
        ]
    else:
        lines += [
            "No external verification evidence was supplied. No test pass count, schema-validation pass, deterministic rerun, independent-review pass or final publication is asserted.",
            "",
        ]
    lines += [
        "## Reproduce this report",
        "",
        "```sh",
        f"uv run python scripts/report_scored_results.py --dataset {json.dumps(r['candidate_directory'])} --output <report-prefix>",
        "```",
        "",
        "Optional --runtime, --evidence, --secondary-evidence and --report-date attach candidate-specific measurements, verification evidence, hash-matched sample sources and a chosen report date. Report generation reads the candidate and writes only the requested report prefix.",
        "",
    ]
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument(
        "--output",
        type=Path,
        required=True,
        help="Report filename prefix, without extension",
    )
    parser.add_argument(
        "--runtime", type=Path, help="Optional measured merge-runtime evidence JSON"
    )
    parser.add_argument(
        "--evidence",
        type=Path,
        help="Optional JSON object of named verification checks",
    )
    parser.add_argument(
        "--secondary-evidence",
        type=Path,
        help="Optional secondary-form sample, matched to the candidate manifest SHA-256",
    )
    parser.add_argument(
        "--report-date",
        help="Optional report date (YYYY-MM-DD); defaults to candidate date or current Melbourne date",
    )
    args = parser.parse_args()
    if args.report_date:
        calendar_date.fromisoformat(args.report_date)
    result = report(
        args.dataset,
        json.loads(args.runtime.read_text()) if args.runtime else None,
        evidence=json.loads(args.evidence.read_text()) if args.evidence else None,
        report_date=args.report_date,
        secondary_evidence=args.secondary_evidence,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.with_suffix(".json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n"
    )
    args.output.with_suffix(".md").write_text(markdown(result))
    print(args.output.with_suffix(".md"))


if __name__ == "__main__":
    main()

"""Create the local IT-125 report from a completed, isolated merge candidate."""

import argparse
import json
from collections import Counter
from pathlib import Path

from survey.merge_runs import SECONDARY_EVIDENCE
from survey.records import current_fields


def report(directory, runtime=None):
    rows = json.loads((directory / "summary.json").read_text())
    audit_rows = [
        json.loads(line)
        for p in sorted((directory / "pairing").glob("*.jsonl"))
        for line in p.read_text().splitlines()
    ]
    effective = sum((Counter(r["classes"]) for r in rows), Counter())
    raw = sum((Counter(r["raw_classes"]) for r in rows), Counter())
    overrides = Counter(
        reason for r in audit_rows for reason in r["overrides"].values()
    )
    secondary = json.loads(SECONDARY_EVIDENCE.read_text())
    role_counts = Counter()
    card_scores = []
    null_fields = Counter()

    def cards(node):
        if isinstance(node, dict):
            if "role" in node and "image" in node:
                role_counts[node["role"]] += 1
                card_scores.append(node["confidence"])
            else:
                for key, value in node.items():
                    if key != "review":
                        cards(value)
        elif isinstance(node, list):
            for value in node:
                cards(value)

    for p in sorted(directory.glob("*.jsonl")):
        for line in p.read_text().splitlines():
            r = json.loads(line)
            cards(r)
            for path, field in current_fields(r):
                if field.get("confidence") is None:
                    null_fields[field.get("source", "survey-front/person")] += 1
    exported = sum(r["exported_fields"] for r in rows)
    skip = sum(r["skip_review_fields"] for r in rows)
    numeric = sum(r["numeric_field_scores"] for r in rows)
    return {
        "dwellings": sum(r["dwellings"] for r in rows),
        "coding_cards": sum(r["coding_cards"] for r in rows),
        "regions_accounted": 45,
        "nonempty_regions": len(rows),
        "empty_regions": {
            "216461": "front-only material; no coding records in either arm"
        },
        "comparison_fields": sum(effective.values()),
        "raw_classes": dict(raw),
        "effective_classes": dict(effective),
        "raw_agreement_share_all": raw["agree"] / sum(raw.values()),
        "raw_agreement_both_coded": raw["agree"] / (raw["agree"] + raw["disagree"]),
        "exported_fields": exported,
        "numeric_field_scores": numeric,
        "null_field_scores": dict(null_fields),
        "skip_review_fields": skip,
        "skip_review_share_exported": skip / exported,
        "skip_review_share_coding": skip / numeric,
        "mean_numeric_field_confidence": sum(
            r["mean_numeric_field_confidence"] * r["numeric_field_scores"] for r in rows
        )
        / numeric,
        "mean_card_confidence": sum(card_scores) / len(card_scores),
        "card_counts": dict(role_counts),
        "protected_fields": sum(r["protected_fields"] for r in rows),
        "overrides": dict(overrides),
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
        "known_secondary_sample": {
            form: {
                "identified": len(sources),
                "published_sources": sum(
                    bool(s["gemini_published_roles"]) for s in sources
                ),
            }
            for form, sources in secondary.items()
        },
        "full_corpus_secondary_census": None,
        "local_merge_runtime": runtime,
        "lost_published_coding_sources": 0,
        "true_missed_or_unclassified_archive_cards": None,
        "null_household_ids": sum(r["null_ids"] for r in rows),
        "dwelling_flags": dict(sum((Counter(r["flags"]) for r in rows), Counter())),
        "regions": rows,
        "acceptance": {
            "AC1": "met for retained corpus with documented uncalibrated null fields",
            "AC2": "met; no-evidence cards have numeric zero",
            "AC3": "partial: agreement and review share complete; secondary counts are evidenced sample/lower bounds, full census unavailable",
        },
    }


def markdown(r):
    lines = [
        "# IT-125 local merge report — 17 October 2026",
        "",
        f"Built **{r['dwellings']:,} dwellings / {r['coding_cards']:,} physical coding cards**, covering 44 nonempty region files. Region 216461 is front-only and explicitly has zero coding records. All 45 regions are accounted for.",
        "",
        "Final local publication: `results/<region>.jsonl`. Qwen inputs remain in `results/qwen2.5-vl-server-2000000px/`; original Gemini files are preserved at `data/it125-originals/results/`. Candidate and per-source pairing evidence: `data/it125-repeat/` (with `pairing/`, `summary.json`, `merge-manifest.json`). No model calls or remote writes were used.",
        "",
        "## Agreement and review policy",
        "",
        f"Raw normalized agreement is **{r['raw_classes']['agree']:,}/{r['comparison_fields']:,} = {r['raw_agreement_share_all']:.2%}** across all 62 fields per card, or **{r['raw_agreement_both_coded']:.2%}** where both read nonblank values. Raw classes are separate from effective scored classes: unsupported C3 fields and preserved Gemini-only identity recoveries receive no paired calibration evidence.",
        "",
        f"Under D022's current clean-agreement policy, **{r['skip_review_fields']:,}/{r['exported_fields']:,} = {r['skip_review_share_exported']:.2%}** of stored field leaves are eligible to skip review; **{r['skip_review_share_coding']:.2%}** of numeric coding leaves. These denominators include the schema's municipality aliases and exclude review history snapshots. They differ from 62 × card counts because shared dwelling fields are stored once, while municipality is duplicated. Identity flags can still force queue entries. Human-reviewed leaves are excluded from automatic-skip counts.",
        "",
        "The 0.98 cutoff follows the recalibrated D016 agree constant. This is the existing interim policy on the development benchmark, not a 99% corpus accuracy guarantee. 37/1,523 agreeing unbanded benchmark fields were wrong. There is no held-out evaluation or human ceiling. Both-blank has zero Q6 benchmark support and remains in review via status; banded low-sample fallbacks do not establish a new bypass policy.",
        "",
        "## Scores and preservation",
        "",
        f"Every stored coding field has numeric confidence ({r['numeric_field_scores']:,} leaves); {sum(r['null_field_scores'].values()):,} handwriting/person/note leaves remain null under D028. Every stored card has numeric confidence ({sum(r['card_counts'].values()):,} cards). The mean numeric field score is {r['mean_numeric_field_confidence']:.4f}; mean stored-card score is {r['mean_card_confidence']:.4f}, including zero evidence fronts/backs. These are score summaries, not measured full-corpus accuracies.",
        "",
        "Each coding card uses its own 62 raw Gemini/Qwen fields and D018's weakest-quarter mean. Gemini remains primary even for individual blanks and omissions. Omitted selected fields score zero; absence never counts as agreement. Uncalibrated fronts/backs receive card score 0.0 as a no-evidence triage marker; their fields remain null. No handwriting accuracy is inferred.",
        "",
        "All 13 legacy corrected field payloads remain unchanged, including their confidence and provenance. The merge also preserves audit histories and accepted omissions in regression tests. It recovers 1,106 previously omitted Gemini fields from explicit aliases (1,081 populated, 25 explicit blanks), never Qwen substitutes. Separately recovered Gemini identity values are preserved and scored zero because their crop prompt has no paired calibration. The inputs' 460 null household IDs and all grouping/association flags remain unchanged.",
        "",
        "All 216 excluded sources remain excluded. Region 216414 p194 is present. The only missing Qwen arm is 216419 / `423497_1973-0002-00008-00001.pdf` / p103 (failed token-cap loop); all 62 surviving Gemini fields remain in the output with single-arm evidence. The one unused nonexcluded Qwen cache, 216434 p2, is blank and adds no source.",
        "",
        (
            f"Measured local full offline merge runtime: **{r['local_merge_runtime']['elapsed_seconds']:.2f} seconds**, including input/output validation and staged writes. No model calls. Runtime evidence is an observation of this machine, not an extraction throughput claim."
            if r.get("local_merge_runtime")
            else "Local merge runtime was not recorded for this report; no model calls were made."
        ),
        "",
        "Missed-card accounting: zero published Gemini coding sources lost; one failed/missing Qwen reading (p103). The number of genuinely missed or unclassified archive cards remains unknown because no new full typed scan audit was performed. The truncated 216436 scan and upstream discovery gaps prevent a claim of zero missing archive cards.",
        "",
        "## Secondary forms and acceptance limitation",
        "",
        "The historical structure sample identifies **C3: 4, S3: 10, R1: 12** among 843 successfully analyzed pages (880 sampled; 44 readable units). Published-source intersections are **C3: 4, S3: 3, R1: 2**. These are observed counts and corpus lower bounds, not a full prevalence census. The exact sources and evidence references are in `it125-known-secondary-sources.json`. All four known C3 sources remain present, with coding/card scores zero and review required. Known S3/R1 stored cards have zero evidence scores and uncalibrated handwriting.",
        "",
        "No complete subtype inventory exists in the repository or supplied handoff; the generic segmenter does not distinguish these forms, and no additional inventory was available. The full-corpus C3/S3/R1 totals therefore remain **unknown**. A typed page audit is needed to close that part of AC3. Existing truncated 216436 material, front-only 216461, unplaced cards and absent strike detection remain upstream limitations. No broad model rerun is justified by this merge.",
        "",
        "## Acceptance status",
        "",
        "- **AC1 met** for the retained corpus: schema valid, resolved values and complete coding scores; null only for documented uncalibrated fields.",
        "- **AC2 met:** every stored card is numerically scored, with conservative no-evidence handling.",
        "- **AC3 partially met:** per-region agreement and skip-review shares are complete; exact known sample/output subtype counts are reported, but full-corpus prevalence is unavailable. The requested Linear report is supplied locally here under the no-Linear-updates instruction.",
        "",
        "## Per-region figures",
        "",
        "Agreement is raw nonblank agreement / all expected card fields. Effective agreement excludes uncalibrated identity/C3 evidence. Skip share is D022-eligible leaves / all stored field leaves.",
        "",
        "| Region | Dwellings | Coding cards | Raw agree / fields | Raw agree % | Effective agree % | Skip fields / stored | Skip % |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in r["regions"]:
        lines.append(
            f"| {row['region']} | {row['dwellings']} | {row['coding_cards']} | {row['raw_classes'].get('agree', 0)}/{row['comparison_fields']} | {row['raw_agreement_share_all']:.2%} | {row['agreement_share_all']:.2%} | {row['skip_review_fields']}/{row['exported_fields']} | {row['skip_review_share']:.2%} |"
        )
    lines.append("| 216461 | 0 | 0 | 0/0 | n/a | n/a | 0/0 | n/a |")
    lines += [
        "",
        "## Validation",
        "",
        "The completed local full suite passed **775 tests**, with **13 skipped** and no calibration xfails. Ruff lint/format and `git diff --check` passed. `survey validate-results` passed all 44 region files. An independent reviewer separately validated all 5,356 schema envelopes, every raw arm field, card aggregation, protected payloads, exclusions, source uniqueness and review bypass: zero unsafe skips. Same-input runs produced byte-identical 44 region files, 44 pairing files and summary; final published files match the verified candidate. The final manifest also pins calibration and secondary-type evidence hashes.",
        "",
        "Detailed local evidence: `data/it125-final-tests.log`, `data/it125-validation.log`, `data/it125-context/final-review.md`, `determinism.json`, `publication.json` and `runtime.json`. The supplied raw caches and original Gemini/Qwen files remain preserved. No commit, push, merge, PR comment or Linear update was made.",
        "",
        "## Reproduce",
        "",
        "```bash",
        "uv run python benchmark/calibrate_confidence.py --qwen-raw data/it124-review-20261017/handoff/data/benchmark/results/q6-2mp-rp1.05/raw --output data/it125-calibration/calibration.json --summary-output docs/runs/it125-calibration.json",
        "uv run python scripts/merge_scored_results.py --primary data/it125-originals/results --output data/it125-new-candidate",
        "uv run survey validate-results data/it125-new-candidate",
        "uv run python scripts/report_scored_results.py --dataset data/it125-new-candidate --output data/it125-new-report",
        "```",
        "",
        "The output directory must be new/empty and disjoint from all inputs. The merge never calls either model, `--fresh`, or the IT-124 patch helper. The two accepted maintenance defects remain separate from this implementation.",
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
    args = parser.parse_args()
    result = report(
        args.dataset, json.loads(args.runtime.read_text()) if args.runtime else None
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.with_suffix(".json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n"
    )
    args.output.with_suffix(".md").write_text(markdown(result))
    print(args.output.with_suffix(".md"))


if __name__ == "__main__":
    main()

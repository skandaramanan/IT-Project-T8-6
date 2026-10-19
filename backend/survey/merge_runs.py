"""Offline IT-125 pairing. The Gemini envelope is the authoritative structure.

Paired evidence lives in an audit JSONL beside the staged dataset, rather than
adding unapproved properties to D007. No extractor/client is constructed here.
"""

from __future__ import annotations

import json
from collections import Counter
from copy import deepcopy
from pathlib import Path

from survey.confidence.agreement import AGREE, NO_SECOND_OPINION, compare_fields
from survey.confidence.card import card_confidence
from survey.confidence.field import score_fields
from survey.extraction.base import ExtractionResult
from survey.extraction.card_fields import FIELD_SCHEMA_BY_NAME
from survey.extraction.json_extraction import (
    parse_confidence_bands,
    with_canonical_labels,
)
from survey.extraction.record import FIELD_MAP, build_field, build_omitted_field
from survey.records import (
    current_fields,
    digest,
    read_dataset,
    validate_records,
    write_atomic,
)
from survey.review.routing import needs_review

GEMINI = "gemini-3.5-flash-lite"
QWEN = "qwen2.5-vl-server-2000000px"
QWEN_CACHE = "qwen-qwen2.5-vl-7b-q6_k"
IDENTITIES = {"Municipality", "Number of Dwelling", "Number of Household"}
SECONDARY_EVIDENCE = (
    Path(__file__).parents[2] / "docs/runs/it125-known-secondary-sources.json"
)
EXPECTED_QWEN = {
    "extractor": QWEN,
    "model": "qwen/qwen2.5-vl-7b",
    "weights": "Q6_K",
    "max_pixels": 2000000,
    "repeat_penalty": 1.05,
    "struck_detection": False,
    "max_tokens": 2048,
    "decoding": "greedy",
    "prompt_sha256": "2ef780a239078c7d",
}


def protected(field):
    # Includes accepted omitted fields and pending/undone audit trails. Never
    # change a payload underneath a human audit snapshot.
    return bool(field.get("review")) or field.get("origin") == "corrected"


def inventory(dataset):
    sources = {}
    for region, (records, _) in dataset.items():
        for record in records:
            for household in record["dwelling"]["households"]:
                cards = [
                    c for c in household.get("cards", []) if c["role"] == "coding-front"
                ]
                if len(cards) != 1:
                    raise ValueError(
                        "Each household must have one physical coding source"
                    )
                card = cards[0]
                source = (region, card["image"], card["page"])
                if source in sources:
                    raise ValueError(f"Duplicate physical source: {source}")
                sources[source] = household
    return sources


def cache_reading(path):
    """Missing file and present-but-failed response remain separate evidence."""
    if not path.exists():
        return None, "absent", None
    raw = path.read_bytes()
    try:
        result = with_canonical_labels(ExtractionResult(**json.loads(raw)))
    except (ValueError, TypeError) as error:
        raise ValueError(f"Invalid cache {path}: {error}") from error
    if not result.fields:
        return None, "failed", digest(raw)
    return result, "available", digest(raw)


def coding_targets(record, index):
    d = record["dwelling"]
    h = d["households"][index]
    for label, (key, group) in FIELD_MAP.items():
        if group in {"dwelling", "house"}:
            if index:
                continue
            fields = d if group == "dwelling" else d["house"]
        else:
            fields = h if group == "household" else h[group]
        yield label, fields[key]
    yield "Municipality", h["municipality"]


def validate_secondary_cache(dataset, cache_root, manifest):
    """Require the published Qwen export to derive from its supplied own cache.

    A physical page and configuration can survive a replaced scan or rerun.
    Compare the semantic fields as well, using each household's own reading and
    only the shared fields its export envelope owns. Never repair the secondary
    export here: a mismatch, including a reviewed mismatch, needs its matching
    raw input before it can supply agreement/confidence evidence.
    """
    for region, (records, _) in dataset.items():
        folder = cache_root / region / QWEN / QWEN_CACHE
        if json.loads((folder / "extractor.json").read_text()) != manifest:
            raise ValueError(f"{region}: cache/result configuration mismatch")
        for record in records:
            for index, household in enumerate(record["dwelling"]["households"]):
                card = next(
                    c for c in household["cards"] if c["role"] == "coding-front"
                )
                source = (region, card["image"], card["page"])
                filename = f"{Path(card['image']).stem}_p{card['page']:04d}.json"
                result, _, _ = cache_reading(folder / filename)
                if result is None:
                    raise ValueError(
                        f"Published Qwen source lacks usable raw cache: {source}"
                    )
                for label, field in coding_targets(record, index):
                    expected = (
                        build_field(
                            FIELD_SCHEMA_BY_NAME[label],
                            result.fields[label],
                            struck=None,
                        )
                        if label in result.fields
                        else build_omitted_field()
                    )
                    if any(
                        field.get(key) != expected[key]
                        for key in ("value", "code", "label", "status")
                    ):
                        review = (
                            " (reviewed field; matching raw evidence required)"
                            if protected(field)
                            else ""
                        )
                        raise ValueError(
                            f"Published Qwen field differs from its raw cache: {source}, "
                            f"{label}{review}; cache may belong to a stale scan or reading"
                        )


def score_household(
    record,
    index,
    first,
    second,
    *,
    first_state="absent",
    second_state="absent",
    unsupported_form=None,
):
    """Score all 62 own raw fields, writing only fields this card owns."""
    a = first.fields if first else None
    b = second.fields if second else None
    pairs = compare_fields(
        a,
        b,
        first_bands=parse_confidence_bands(first.raw_text) if first else None,
        second_bands=parse_confidence_bands(second.raw_text) if second else None,
        first_state=first_state,
        second_state=second_state,
    )
    scores = score_fields(pairs, {"a": GEMINI, "b": "qwen2.5-vl"})
    if unsupported_form:
        for score in scores.values():
            score.update(confidence=0.0, source_agreement=NO_SECOND_OPINION)
    overrides = {}
    for label, field in coding_targets(record, index):
        if protected(field):
            overrides[label] = "human_review_preserved"
            continue
        selected = first if first is not None else second
        expected = (
            build_field(
                FIELD_SCHEMA_BY_NAME[label], selected.fields[label], struck=None
            )
            if selected and label in selected.fields
            else build_omitted_field()
        )
        if any(
            field.get(k) != expected[k] for k in ("value", "code", "label", "status")
        ):
            if (
                first is not None
                and field["status"] == "omitted"
                and label in first.fields
            ):
                field.update(expected)
                overrides[label] = "primary_label_alias_recovered"
            elif first is not None and label in IDENTITIES:
                # Gemini's separate crop reread/identity recovery has no paired
                # Qwen reading or calibrated crop accuracy. Keep the published
                # identity, explicitly score its different configuration zero.
                scores[label].update(
                    value=field["value"],
                    confidence=0.0,
                    source_agreement=NO_SECOND_OPINION,
                )
                overrides[label] = "gemini_identity_recovery_uncalibrated"
            elif first is None and second is not None:
                # Only a wholly unavailable Gemini arm permits substitution.
                field.update(expected)
            else:
                raise ValueError(
                    f"Published primary field differs from its raw reading: {label}"
                )
        field["confidence"] = scores[label]["confidence"]
    h = record["dwelling"]["households"][index]
    for card in h["cards"]:
        if card["role"] == "coding-front":
            card["confidence"] = card_confidence(
                s["confidence"] for s in scores.values()
            )
    return pairs, scores, overrides


def _zero_unscored_cards(node):
    if isinstance(node, dict):
        if "role" in node and "image" in node:
            if node["role"] != "coding-front" or node.get("confidence") is None:
                node["confidence"] = 0.0
            return
        for key, child in node.items():
            if key != "review":
                _zero_unscored_cards(child)
    elif isinstance(node, list):
        for child in node:
            _zero_unscored_cards(child)


def merge_region(region, records, gemini_cache, qwen_cache, known_failures=frozenset()):
    merged = deepcopy(records)
    audit = []
    secondary = json.loads(SECONDARY_EVIDENCE.read_text())
    unsupported = {
        (r["region"], r["pdf"], r["page"]): form
        for form, rows in secondary.items()
        for r in rows
    }
    for record in merged:
        for index, household in enumerate(record["dwelling"]["households"]):
            card = next(c for c in household["cards"] if c["role"] == "coding-front")
            source = (region, card["image"], card["page"])
            filename = f"{Path(card['image']).stem}_p{card['page']:04d}.json"
            a, a_state, a_hash = cache_reading(gemini_cache / filename)
            b, b_state, b_hash = cache_reading(qwen_cache / filename)
            # The pipeline never caches failed requests. This known failure is
            # not an absent/unattempted reading and must remain explicit.
            if b_state == "absent" and source in known_failures:
                b_state = "failed"
            if a is None:
                raise ValueError(
                    f"Published Gemini source has no usable primary cache: {source}"
                )
            if parse_confidence_bands(a.raw_text) or a.struck is not None:
                raise ValueError(
                    f"{source}: primary cache is not D028 unbanded/no-struck"
                )
            pairs, scores, overrides = score_household(
                record,
                index,
                a,
                b,
                first_state=a_state,
                second_state=b_state,
                unsupported_form=unsupported.get(source),
            )
            audit.append(
                {
                    "region": region,
                    "pdf": card["image"],
                    "page": card["page"],
                    "primary_state": a_state,
                    "secondary_state": b_state,
                    "primary_sha256": a_hash,
                    "secondary_sha256": b_hash,
                    "fields": {
                        label: {**pair, **scores[label]}
                        for label, pair in pairs.items()
                    },
                    "overrides": overrides,
                    "unsupported_form": unsupported.get(source),
                    "card_confidence": card["confidence"],
                }
            )
        _zero_unscored_cards(record)
    validate_records(merged, region)
    # Structural and semantic preservation: the only permitted envelope change
    # in a supplied Gemini corpus is unprotected confidence.
    before, after = deepcopy(records), deepcopy(merged)
    for old, new in zip(before, after):
        for (old_path, old_field), (new_path, new_field) in zip(
            current_fields(old), current_fields(new)
        ):
            if old_path != new_path:
                raise ValueError(f"{region}: field ownership changed")
            if not protected(old_field) and old_field["status"] == "omitted":
                old_field.update(deepcopy(new_field))
    for collection in (before, after):
        for record in collection:
            for _, field in current_fields(record):
                if not protected(field):
                    field["confidence"] = None
            _clear_card_scores(record)
    if before != after:
        raise ValueError(f"{region}: merge changed Gemini structure or protected data")
    return merged, audit


def _clear_card_scores(node):
    if isinstance(node, dict):
        if "role" in node and "image" in node:
            node["confidence"] = None
        else:
            for key, value in node.items():
                if key != "review":
                    _clear_card_scores(value)
    elif isinstance(node, list):
        for value in node:
            _clear_card_scores(value)


def _write_json(path, data):
    write_atomic(path, json.dumps(data, indent=2, sort_keys=True) + "\n")


def merge_dataset(primary, secondary, gemini_cache, qwen_cache, output, excluded_path):
    """Prepare and validate everything before writing any staged region."""
    output = output.resolve()
    for input_path in (primary, secondary, gemini_cache, qwen_cache):
        resolved = input_path.resolve()
        if (
            output == resolved
            or output in resolved.parents
            or resolved in output.parents
        ):
            raise ValueError("Staging output must be isolated from every input")
    if output.exists() and any(output.iterdir()):
        raise ValueError("Staging output must be new or empty")
    first = read_dataset(sorted(primary.glob("*.jsonl")))
    second = read_dataset(sorted(secondary.glob("*.jsonl")))
    a_sources, b_sources = inventory(first), inventory(second)
    excluded = {
        (r["region"], r["pdf"], r["page"])
        for r in json.loads(excluded_path.read_text())
    }
    if excluded & (a_sources.keys() | b_sources.keys()):
        raise ValueError("An excluded source is still published")
    if extra := b_sources.keys() - a_sources.keys():
        raise ValueError(f"Qwen has unpublished primary sources: {sorted(extra)}")
    manifest = json.loads((secondary / "extractor.json").read_text())
    if manifest != EXPECTED_QWEN:
        raise ValueError(
            "Qwen results configuration is not the calibrated Q6 2MP configuration"
        )
    known_failures = {("216419", "423497_1973-0002-00008-00001.pdf", 103)}
    if missing := (a_sources.keys() - b_sources.keys()) - known_failures:
        raise ValueError(f"Unexpected missing Qwen output sources: {sorted(missing)}")
    # Validate all secondary readings before scoring any region. Configuration
    # and source coverage alone cannot detect a rerun of a same-named PDF.
    validate_secondary_cache(second, qwen_cache, manifest)
    staged, audits, summary = {}, [], []
    for region, (records, _) in first.items():
        qfolder = qwen_cache / region / QWEN / QWEN_CACHE
        if json.loads((qfolder / "extractor.json").read_text()) != manifest:
            raise ValueError(f"{region}: cache/result configuration mismatch")
        merged, audit = merge_region(
            region, records, gemini_cache / region / GEMINI, qfolder, known_failures
        )
        for row in audit:
            source = (region, row["pdf"], row["page"])
            if source in b_sources and row["secondary_state"] != "available":
                raise ValueError(
                    f"Published Qwen source lacks usable raw cache: {source}"
                )
            if source not in b_sources and row["secondary_state"] == "available":
                raise ValueError(
                    f"Unpublished Qwen reading unexpectedly available: {source}"
                )
        counts = Counter(
            f["source_agreement"] for row in audit for f in row["fields"].values()
        )
        raw_counts = Counter(
            f["agreement"] for row in audit for f in row["fields"].values()
        )
        fields = [f for r in merged for _, f in current_fields(r)]
        skip = sum(not protected(f) and not needs_review(f) for f in fields)
        total = sum(counts.values())
        coded = counts[AGREE] + counts["disagree"]
        summary.append(
            {
                "region": region,
                "dwellings": len(records),
                "coding_cards": len(audit),
                "classes": dict(counts),
                "raw_classes": dict(raw_counts),
                "raw_agreement_share_all": raw_counts[AGREE] / total,
                "comparison_fields": total,
                "agreement_share_all": counts[AGREE] / total,
                "agreement_both_coded": counts[AGREE] / coded if coded else None,
                "exported_fields": len(fields),
                "skip_review_fields": skip,
                "skip_review_share": skip / len(fields),
                "flags": dict(
                    Counter(
                        flag for r in records for flag in r["dwelling"].get("flags", [])
                    )
                ),
                "null_ids": sum(
                    h["record_id"] is None
                    for r in records
                    for h in r["dwelling"]["households"]
                ),
                "protected_fields": sum(protected(f) for f in fields),
                "numeric_field_scores": sum(
                    f.get("confidence") is not None for f in fields
                ),
                "mean_numeric_field_confidence": sum(
                    f["confidence"] for f in fields if f.get("confidence") is not None
                )
                / sum(f.get("confidence") is not None for f in fields),
            }
        )
        staged[region] = merged
        audits.extend(audit)
    output.mkdir(parents=True, exist_ok=True)
    audit_dir = output / "pairing"
    audit_dir.mkdir()
    for region, records in staged.items():
        write_atomic(
            output / f"{region}.jsonl", "".join(json.dumps(r) + "\n" for r in records)
        )
        write_atomic(
            audit_dir / f"{region}.jsonl",
            "".join(json.dumps(r) + "\n" for r in audits if r["region"] == region),
        )
    _write_json(output / "summary.json", summary)
    _write_json(
        output / "merge-manifest.json",
        {
            "primary": GEMINI,
            "secondary": manifest,
            "primary_files": {
                p.name: digest(p.read_bytes()) for p in sorted(primary.glob("*.jsonl"))
            },
            "secondary_files": {
                p.name: digest(p.read_bytes())
                for p in sorted(secondary.glob("*.jsonl"))
            },
            "excluded_sha256": digest(excluded_path.read_bytes()),
            "calibration_sha256": digest(
                (SECONDARY_EVIDENCE.parent / "it125-calibration.json").read_bytes()
            ),
            "secondary_type_evidence_sha256": digest(SECONDARY_EVIDENCE.read_bytes()),
            "missing_secondary": [
                list(s) for s in sorted(a_sources.keys() - b_sources.keys())
            ],
            "excluded_sources": len(excluded),
            "card_without_calibrated_fields": 0.0,
            "policy": "D021 Gemini primary, D016 normalized Q6 calibration, D018 weakest quarter, D022 clean agreement",
        },
    )
    return summary

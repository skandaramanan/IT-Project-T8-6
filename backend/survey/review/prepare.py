"""Representation-only preparation from published records and retained readings.

This module never imports pipeline, model clients or confidence scorers. Missing
per-card data stays omitted; a secondary export is not a primary reading.
"""

import json
import math
from collections import Counter
from copy import deepcopy
from pathlib import Path

from survey.extraction.base import ExtractionResult
from survey.extraction.json_extraction import with_canonical_labels
from survey.extraction.record import FIELD_MAP, build_omitted_field, build_record
from survey.records import (
    REGION,
    current_fields,
    digest,
    read_dataset,
    safe_pdf,
    validate_records,
    write_atomic,
)
from survey.review import relinking as model
from survey.review.flags import build_flags


def prepare_records(records, readings=None, evidence=None):
    """Return new records and a reproducible source/payload preservation receipt.

    readings: (region, PDF basename, page) -> retained primary fields/struck dict.
    evidence: same source -> field label -> {value, confidence}, already measured.
    """
    readings, evidence = readings or {}, evidence or {}
    candidate = deepcopy(records)
    report = {
        "cards": 0,
        "recovered_fields": [],
        "missing_fields": [],
        "preserved_fields": [],
        "alias_mappings": [],
        "protected_fields": 0,
        "preserved_cards": [],
        "derived_identity_changes": [],
        "derived_note_reference_changes": [],
    }
    for old, new in zip(records, candidate):
        if old["schema_version"] == model.REVIEW_SCHEMA:
            raise ValueError(
                "Input is already prepared; start from pinned published results"
            )
        if any("review" in f for _, f in current_fields(old)):
            raise ValueError(
                "Published input contains review history; reconcile reviewer work before preparing a fresh seed"
            )
        d = new["dwelling"]
        for hi, h in enumerate(d["households"]):
            c = model.coding_source(h)
            key = (new["region"], c["image"], c["page"])
            raw = readings.get(key)
            if raw is not None:
                if not isinstance(raw.get("fields", {}), dict):
                    raise ValueError(f"{key}: retained primary fields must be a map")
                normalized = with_canonical_labels(
                    ExtractionResult(
                        fields=raw.get("fields", {}),
                        raw_text=raw.get("raw_text"),
                        struck=raw.get("struck"),
                    )
                )
                raw = {**raw, "fields": normalized.fields, "struck": normalized.struck}
            recovered = (
                build_record(
                    raw.get("fields", {}),
                    region=key[0],
                    image=key[1],
                    page=key[2],
                    struck=raw.get("struck"),
                )
                if raw is not None
                else None
            )
            # build_record gives the card its own readings (schema 0.7.0).
            own = recovered["dwelling"]["households"][0] if recovered else None
            if hi == 0:
                if "municipality" in h and h["municipality"] != d["municipality"]:
                    raise ValueError(
                        f"{key}: municipality alias payloads disagree; reconcile their source evidence"
                    )
                h["municipality"] = deepcopy(d["municipality"])
                h["dwelling_no"] = deepcopy(d["dwelling_no"])
                h["house"] = deepcopy(d.get("house", {}))
            else:
                if "municipality" not in h:
                    h["municipality"] = (
                        deepcopy(own["municipality"])
                        if own
                        else build_omitted_field(source="coding-front")
                    )
                h["dwelling_no"] = (
                    deepcopy(own["dwelling_no"])
                    if own
                    else build_omitted_field(source="coding-front")
                )
                h["house"] = (
                    deepcopy(own["house"])
                    if own
                    else {
                        name: build_omitted_field()
                        for name, group in FIELD_MAP.values()
                        if group == "house"
                    }
                )
                for label, (name, group) in FIELD_MAP.items():
                    if label != "Number of Dwelling" and group != "house":
                        continue
                    f = h["dwelling_no"] if group == "dwelling" else h["house"][name]
                    measured = evidence.get(key, {}).get(label)
                    if (
                        raw is not None
                        and label in raw.get("fields", {})
                        and measured
                        and measured.get("value") == f["value"]
                    ):
                        f["confidence"] = measured["confidence"]
                    report[
                        "recovered_fields"
                        if raw is not None and label in raw.get("fields", {})
                        else "missing_fields"
                    ].append(
                        {
                            "source": list(key),
                            "field": label,
                            "confidence": f["confidence"],
                        }
                    )
                if any(row["source"] == list(key) for row in report["missing_fields"]):
                    h["flags"] = sorted(
                        set(h.get("flags", [])) | {"missing_card_reading"}
                    )
            report["cards"] += 1
        for path, field in current_fields(old):
            target = path
            if path[:2] in {
                ("dwelling", "municipality"),
                ("dwelling", "dwelling_no"),
                ("dwelling", "house"),
            }:
                target = ("dwelling", "households", 0, *path[1:])
            node = new
            for part in target:
                node = node[part]
            if node != field:
                raise ValueError(f"Published payload changed at {old['region']} {path}")
            mapping = {
                "region": old["region"],
                "source_coding_cards": [
                    [c["image"], c["page"]]
                    for original in old["dwelling"]["households"]
                    for c in original.get("cards", [])
                    if c["role"] == "coding-front"
                ],
                "source_path": list(path),
                "target_path": list(target),
                "sha256": model.canonical_hash(field),
            }
            report["preserved_fields"].append(mapping)
            report["protected_fields"] += field.get("origin") == "corrected"
            if path[:2] == ("dwelling", "municipality"):
                report["alias_mappings"].append(mapping)
        for key in ("municipality", "dwelling_no", "house"):
            d.pop(key, None)
        new["schema_version"] = model.REVIEW_SCHEMA
    # Note links resolve against the published IDs, before they are re-derived.
    model.finish_records(candidate)
    for old, new in zip(records, candidate):
        old_cards = old["dwelling"].get("cards", []) + [
            c for h in old["dwelling"]["households"] for c in h.get("cards", [])
        ]
        new_cards = new["dwelling"].get("cards", []) + [
            c for h in new["dwelling"]["households"] for c in h.get("cards", [])
        ]
        if old_cards != new_cards:
            raise ValueError(
                "A published source card payload or score changed during preparation"
            )
        report["preserved_cards"].extend(
            {
                "region": old["region"],
                "role": c["role"],
                "pdf": c["image"],
                "page": c.get("page"),
                "sha256": model.canonical_hash(c),
            }
            for c in old_cards
        )
        for previous, current in zip(
            old["dwelling"]["households"], new["dwelling"]["households"]
        ):
            if previous["record_id"] != current["record_id"]:
                card = model.coding_source(current)
                report["derived_identity_changes"].append(
                    {
                        "source": [new["region"], card["image"], card["page"]],
                        "before": previous["record_id"],
                        "after": current["record_id"],
                    }
                )
        for previous, current in zip(
            old["dwelling"].get("notes", []), new["dwelling"].get("notes", [])
        ):
            if previous["household_id"] != current["household_id"]:
                report["derived_note_reference_changes"].append(
                    {
                        "region": old["region"],
                        "front_page": current["front_page"],
                        "page": current["page"],
                        "before": previous["household_id"],
                        "after": current["household_id"],
                    }
                )
    for region in {r["region"] for r in candidate}:
        validate_records([r for r in candidate if r["region"] == region], region)
    before = Counter(
        (r["region"], c["image"], c["page"])
        for r in records
        for h in r["dwelling"]["households"]
        for c in h.get("cards", [])
        if c["role"] == "coding-front"
    )
    after = Counter(
        (r["region"], c["image"], c["page"])
        for r in candidate
        for h in r["dwelling"]["households"]
        for c in h.get("cards", [])
        if c["role"] == "coding-front"
    )
    if before != after or any(v != 1 for v in after.values()):
        raise ValueError("Physical coding inventory was not preserved exactly once")
    report["duplicate_groups"] = len(model.duplicate_index(candidate))
    flags, skipped = build_flags(
        {
            region: [r for r in candidate if r["region"] == region]
            for region in {r["region"] for r in candidate}
        }
    )
    if skipped:
        raise ValueError("Prepared queue has invalid owners: " + "; ".join(skipped))
    report["queued_fields"] = len(flags)
    return candidate, report


def prepare_dataset(
    previous: Path,
    output: Path,
    cache: Path | None = None,
    evidence_path: Path | None = None,
):
    """Write only to a fresh staging directory outside the published input tree."""
    previous, output = previous.resolve(), output.resolve()
    if (
        output == previous
        or output.is_relative_to(previous)
        or previous.is_relative_to(output)
    ):
        raise ValueError("Staging output must be separate from the input tree")
    if output.exists() and any(output.iterdir()):
        raise ValueError("Choose a new or empty staging directory")
    regions = read_dataset(sorted(previous.glob("*.jsonl")))
    readings, artifact_hashes, evidence = {}, {}, {}
    if cache is not None:
        for region in sorted(regions):
            folder = cache / region / "gemini-3.5-flash-lite"
            for path in sorted(folder.glob("*.json")):
                if path.name.startswith("._"):
                    continue
                pdf, page = path.stem.rsplit("_p", 1)
                raw = path.read_bytes()
                readings[region, pdf + ".pdf", int(page)] = json.loads(raw)
                artifact_hashes[str(path.relative_to(cache))] = digest(raw)
    evidence_bytes = evidence_path.read_bytes() if evidence_path else None
    if evidence_bytes is not None:
        rows = json.loads(evidence_bytes)
        if not isinstance(rows, list):
            raise ValueError("Measured confidence must be a JSON array of source rows")
        for row in rows:
            if (
                not isinstance(row, dict)
                or not {"region", "pdf", "page", "fields"} <= row.keys()
            ):
                raise ValueError(
                    "Measured confidence needs region, pdf, page and fields"
                )
            if (
                not isinstance(row["region"], str)
                or not REGION.fullmatch(row["region"])
                or not isinstance(row["pdf"], str)
                or not safe_pdf(row["pdf"])
                or type(row["page"]) is not int
                or row["page"] < 1
                or not isinstance(row["fields"], dict)
            ):
                raise ValueError("Measured confidence has an invalid physical source")
            for label, measured in row["fields"].items():
                if (
                    label not in FIELD_MAP
                    or not isinstance(measured, dict)
                    or not {"value", "confidence"} <= measured.keys()
                ):
                    raise ValueError(
                        "Measured confidence needs a known field label, value and confidence"
                    )
                value, score = measured["value"], measured["confidence"]
                if (value is not None and not isinstance(value, str)) or (
                    score is not None
                    and (
                        type(score) not in {int, float}
                        or not math.isfinite(score)
                        or not 0 <= score <= 1
                    )
                ):
                    raise ValueError(
                        "Measured confidence values must be strings/null and scores in [0, 1]/null"
                    )
            key = row["region"], row["pdf"], row["page"]
            if key in evidence:
                raise ValueError(f"Duplicate measured-confidence source: {key}")
            evidence[key] = row["fields"]
    prepared, report = prepare_records(
        [r for records, _ in regions.values() for r in records], readings, evidence
    )
    report.update(
        schema_version=model.REVIEW_SCHEMA,
        input_sha256={region: version for region, (_, version) in regions.items()},
        primary_artifact_sha256=artifact_hashes,
        field_evidence_sha256=digest(evidence_bytes)
        if evidence_bytes is not None
        else None,
    )
    # Finish all recovery/validation before creating output. This is staging,
    # not an application transaction or permission to publish a replacement seed.
    output.mkdir(parents=True, exist_ok=True)
    for region in sorted(regions):
        rows = [r for r in prepared if r["region"] == region]
        write_atomic(
            output / f"{region}.jsonl",
            "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows),
        )
    write_atomic(
        output / "preparation-report.json",
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
    )
    return report

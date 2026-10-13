"""Read teammate-supplied flags. This module never selects or ranks fields."""

import json
from pathlib import Path

from survey.records import REGION, Reference, ReviewError, safe_pdf


def load_queue(path: Path) -> tuple[list[Reference], list[dict]]:
    references, diagnostics, seen = [], [], set()
    try:
        lines = path.read_text(encoding="utf-8-sig").splitlines()
    except OSError as error:
        raise ReviewError(
            "missing_flags", f"Cannot read flagged JSONL: {path}"
        ) from error
    for number, line in enumerate(lines, 1):
        if not line.strip():
            continue
        entry = {}
        try:
            entry = json.loads(line)
            if not isinstance(entry, dict) or set(entry) - {
                "region",
                "pdf",
                "page",
                "field_path",
                "reason",
            }:
                raise ValueError(
                    "Expected region, pdf, page, field_path, and optional reason"
                )
            if any(
                not isinstance(entry.get(k), str)
                for k in ("region", "pdf", "field_path")
            ) or not isinstance(entry.get("reason", ""), str):
                raise ValueError("Reference names and reason must be strings")
            ref = Reference(**entry)
            key = ref.region, ref.pdf, ref.page, ref.field_path
            if key not in seen:
                references.append(ref)
                seen.add(key)
        except (ValueError, TypeError) as error:
            region = entry.get("region") if isinstance(entry, dict) else None
            batch = entry.get("pdf") if isinstance(entry, dict) else None
            region = (
                region if isinstance(region, str) and REGION.fullmatch(region) else None
            )
            batch = (
                batch if region and isinstance(batch, str) and safe_pdf(batch) else None
            )
            diagnostics.append(
                {
                    "line": number,
                    "code": getattr(error, "code", "invalid_reference"),
                    "message": str(error),
                    "region": region,
                    "batch": batch,
                }
            )
    return references, diagnostics

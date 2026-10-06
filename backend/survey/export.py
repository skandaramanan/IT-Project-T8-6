"""D007 records to and from ``results/<region>.jsonl`` (FR-15, IT-66).

One dwelling per line, keyed by municipality and dwelling number. Writing
merges into what is already there rather than replacing it, so:

- a rerun updates its dwellings in place instead of duplicating them (NFR-04);
- households of one dwelling read from separate coding cards, or separate
  runs, end up on the same line;
- a field a reviewer corrected is never overwritten by a machine value (NFR-05).

Every record is validated against the envelope first. One that fails is
reported with its record_id and the failing field path, and not written.
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

# ponytail: repo-relative, which holds for the editable install uv makes. Move
# the schema into the package if survey is ever installed from a wheel.
SCHEMA_PATH = Path(__file__).parents[2] / "schema" / "record-envelope.schema.json"
_VALIDATOR = Draft202012Validator(json.loads(SCHEMA_PATH.read_text()))


def validate(record: dict[str, Any]) -> list[str]:
    """Every way ``record`` breaks the envelope, as ``"<path>: <reason>"``."""
    return [
        f"{'/'.join(map(str, error.absolute_path)) or '<record>'}: {error.message}"
        for error in _VALIDATOR.iter_errors(record)
    ]


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line]


def exported_scans(path: Path) -> set[str]:
    """Scan files that already have a household in ``path``, for resuming."""
    return {
        card["image"]
        for record in read_jsonl(path)
        for household in record["dwelling"]["households"]
        for card in household.get("cards", [])
    }


def write_jsonl(path: Path, records: Iterable[dict[str, Any]]) -> list[str]:
    """Merge ``records`` into ``path``; return one failure per invalid record."""
    lines = {_key(record): record for record in read_jsonl(path)}
    failures = []
    for record in records:
        if errors := validate(record):
            failures.append(f"{_record_id(record)}: {'; '.join(errors)}")
            continue
        key = _key(record)
        lines[key] = _merge(lines[key], record) if key in lines else record

    # Written whole then swapped in, so an interrupted run leaves the old file
    # intact. Sorted, so a rerun's git diff shows only what changed (D025).
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text("".join(json.dumps(lines[key]) + "\n" for key in sorted(lines)))
    os.replace(tmp, path)
    return failures


def _record_id(record: dict[str, Any]) -> str:
    try:
        return record["dwelling"]["households"][0]["record_id"]
    except (KeyError, IndexError, TypeError):
        return "<no record_id>"


def _key(record: dict[str, Any]) -> str:
    """``27-0006`` from ``27-0006-01``: the dwelling, not the household."""
    return _record_id(record).rsplit("-", 1)[0]


def _merge(old: Any, new: Any) -> Any:
    """The new reading wins, except where a reviewer corrected the old one and
    the new one is only a machine value."""
    if _corrected(old) and not _corrected(new):
        return old
    if isinstance(old, dict) and isinstance(new, dict):
        merged = {k: _merge(old[k], v) if k in old else v for k, v in new.items()}
        # A corrected field the new reading no longer has (a renamed field) stays.
        return merged | {k: v for k, v in old.items() if k not in new and _corrected(v)}
    if isinstance(old, list) and isinstance(new, list):
        if any(isinstance(item, dict) and "record_id" in item for item in old + new):
            # Households: matched by record_id, and one not in this reading kept.
            by_id = {h["record_id"]: h for h in old}
            for h in new:
                rid = h["record_id"]
                by_id[rid] = _merge(by_id[rid], h) if rid in by_id else h
            return [by_id[rid] for rid in sorted(by_id)]
        return [_merge(o, n) for o, n in zip(old, new)] + new[len(old) :]
    return new


def _corrected(value: Any) -> bool:
    return isinstance(value, dict) and value.get("origin") == "corrected"

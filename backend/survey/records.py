"""Shared JSONL validation, physical-card lookup, and atomic persistence."""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from threading import RLock
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

from survey.extraction.record import FIELD_MAP

SCHEMA_PATH = Path(__file__).parents[2] / "schema" / "record-envelope.schema.json"
FORMATS = FormatChecker()


@FORMATS.checks("date-time", raises=(ValueError, TypeError))
def valid_timestamp(value):
    if not isinstance(value, str):
        return True
    if not re.fullmatch(
        r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]+)?(?:Z|\+00:00)",
        value,
    ):
        return False
    return datetime.fromisoformat(value).utcoffset() == timedelta(0)


VALIDATOR = Draft202012Validator(
    json.loads(SCHEMA_PATH.read_text(encoding="utf-8")), format_checker=FORMATS
)
REGION = re.compile(r"[a-z0-9][a-z0-9_-]*")


class ReviewError(ValueError):
    def __init__(self, code: str, message: str, status: int = 422):
        super().__init__(message)
        self.code, self.status = code, status


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def schema_errors(record: dict) -> list[str]:
    errors = [
        f"{'/'.join(map(str, e.absolute_path)) or '<record>'}: {e.message}"
        for e in VALIDATOR.iter_errors(record)
    ]
    if record.get("schema_version") in {"0.1.0", "0.2.0", "0.3.0"} and any(
        "review" in field for _, field in current_fields(record)
    ):
        errors.append("Review metadata requires schema 0.4.0")
    return errors


def validate_records(records: list[dict], region: str) -> None:
    seen = set()
    for number, record in enumerate(records, 1):
        if errors := schema_errors(record):
            raise ReviewError(
                "invalid_records", f"record {number}: {'; '.join(errors)}"
            )
        if record["region"] != region:
            raise ReviewError(
                "wrong_region", f"record {number} does not belong to {region}"
            )
        for _, field in current_fields(record):
            validate_history(field)
        for household in record["dwelling"]["households"]:
            for card in household.get("cards", []):
                if card["role"] != "coding-front":
                    continue
                key = card["image"], card.get("page")
                if key in seen:
                    raise ReviewError("ambiguous_card", f"duplicate coding card {key}")
                seen.add(key)
    audit_index({region: records})


def audit_index(regions: dict[str, list[dict]]) -> tuple[dict, dict]:
    """Build one dataset-wide registry, reporting both duplicate locations."""
    requests, decisions, locations = {}, {}, {}
    for region, records in regions.items():
        for number, record in enumerate(records, 1):
            for path, field in current_fields(record):
                location = f"{region}.jsonl record {number} /{'/'.join(map(str, path))}"
                for event in field.get("review", {}).get("history", []):
                    for key, index in (("request_id", requests), ("id", decisions)):
                        identity = (key, event[key])
                        if identity in locations:
                            raise ReviewError(
                                "invalid_history",
                                f"Duplicate audit {key}: {locations[identity]} and {location}",
                            )
                        locations[identity] = location
                        index[event[key]] = event
    return requests, decisions


def validate_history(field: dict) -> None:
    review = field.get("review")
    if not review:
        return
    active, seen_ids, seen_requests = [], set(), set()
    previous_state = "pending"
    previous_payload = None
    item_id = review["history"][0]["item_id"]
    for event in review["history"]:
        if event["id"] in seen_ids or event["request_id"] in seen_requests:
            raise ReviewError(
                "invalid_history", "Duplicate audit decision or request ID"
            )
        seen_ids.add(event["id"])
        seen_requests.add(event["request_id"])
        if (
            event["before_state"] != previous_state
            or event["request"]["action"] != event["action"]
            or event["item_id"] != item_id
        ):
            raise ReviewError(
                "invalid_history", "Audit states or request action are inconsistent"
            )
        if previous_state != "pending" and event["before"] != previous_payload:
            raise ReviewError(
                "invalid_history", "Active audit snapshots are not continuous"
            )
        if event["action"] != "correct" and event["request"]["value"] is not None:
            raise ReviewError(
                "invalid_history", "Only correction accepts a requested value"
            )
        if event["action"] == "undo":
            if (
                not active
                or active[-1]["id"] != event["undo_target"]
                or event["request"]["undo_target"] != event["undo_target"]
            ):
                raise ReviewError(
                    "invalid_history", "Undo must target the latest active decision"
                )
            target = active.pop()
            if (
                event["after"] != target["before"]
                or event["after_state"] != target["before_state"]
            ):
                raise ReviewError(
                    "invalid_history", "Undo does not restore the target snapshot"
                )
        else:
            expected = "accepted" if event["action"] == "accept" else "corrected"
            if (
                event["after_state"] != expected
                or event["request"]["undo_target"] is not None
                or "undo_target" in event
            ):
                raise ReviewError(
                    "invalid_history", "Decision has an invalid review state"
                )
            if event["action"] == "accept" and event["before"] != event["after"]:
                raise ReviewError(
                    "invalid_history", "Acceptance must preserve the field payload"
                )
            if event["action"] in {"correct", "no_data", "illegible"}:
                before, after = event["before"], event["after"]
                expected_payload = deepcopy(before)
                if event["action"] == "correct":
                    value = event["request"]["value"]
                    if not isinstance(value, str) or not re.fullmatch(
                        r"[0-9]{1,64}", value
                    ):
                        raise ReviewError(
                            "invalid_history", "Correction must request exact digits"
                        )
                    expected_payload.update(value=value, status="ok")
                    # Decoding is field-specific; validate the preserved envelope
                    # here without imposing a closed field set on old records.
                    for key in ("code", "label"):
                        if key in after:
                            expected_payload[key] = after[key]
                        else:
                            expected_payload.pop(key, None)
                else:
                    expected_payload.update(
                        value=None, status=event["action"], code=None, label=None
                    )
                expected_payload.setdefault(
                    "original_value", before.get("original_value", before["value"])
                )
                expected_payload["origin"] = "corrected"
                if after != expected_payload:
                    raise ReviewError(
                        "invalid_history",
                        "Decision payload disagrees with its request or provenance",
                    )
            active.append(event)
        previous_state = event["after_state"]
        previous_payload = event["after"]
    if review["state"] != previous_state:
        raise ReviewError(
            "invalid_history", "Current review state disagrees with its history"
        )
    if (
        review["state"] != "pending"
        and {k: v for k, v in field.items() if k != "review"}
        != review["history"][-1]["after"]
    ):
        raise ReviewError(
            "invalid_history",
            "An active reviewed payload changed outside its audit history",
        )


def parse_records(raw: bytes, region: str, name: str) -> tuple[list[dict], str]:
    try:
        records = [
            json.loads(line)
            for line in raw.decode("utf-8-sig").splitlines()
            if line.strip()
        ]
    except (ValueError, UnicodeError) as error:
        raise ReviewError("invalid_records", f"Cannot read {name}: {error}") from error
    validate_records(records, region)
    return records, digest(raw)


def read_records(path: Path, region: str) -> tuple[list[dict], str]:
    try:
        raw = path.read_bytes()
    except OSError as error:
        raise ReviewError(
            "invalid_records", f"Cannot read {path.name}: {error}"
        ) from error
    return parse_records(raw, region, path.name)


def validate_dataset(regions: dict[str, tuple[list[dict], str]]) -> None:
    """Check cross-file constraints after parse_records validated each file."""
    if not regions:
        raise ReviewError("missing_records", "No region JSONL found")
    for region, (records, _) in regions.items():
        if not records:
            raise ReviewError("empty_records", f"{region}.jsonl contains no records")
    audit_index({region: records for region, (records, _) in regions.items()})


def read_dataset(paths: list[Path]) -> dict[str, tuple[list[dict], str]]:
    candidate = {}
    for path in paths:
        if not REGION.fullmatch(path.stem) or path.is_symlink():
            raise ReviewError(
                "invalid_path", f"Unsupported region JSONL path: {path.name}"
            )
        if path.stem in candidate:
            raise ReviewError("invalid_path", f"Duplicate region file: {path.name}")
        candidate[path.stem] = read_records(path, path.stem)
    validate_dataset(candidate)
    return candidate


def write_atomic(path: Path, text: str) -> None:
    """A failed flush/replace leaves the original intact; temp is on its filesystem."""
    tmp = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            prefix=f".{path.name}.",
            suffix=".tmp",
            dir=path.parent,
            delete=False,
        ) as stream:
            tmp = Path(stream.name)
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp, path)
    finally:
        if tmp is not None:
            tmp.unlink(missing_ok=True)


def safe_pdf(name: str) -> bool:
    return bool(
        name
        and name.lower().endswith(".pdf")
        and not any(c in name for c in "/\\:")
        and name not in {".", ".."}
    )


@dataclass(frozen=True)
class Reference:
    region: str
    pdf: str
    page: int
    field_path: str
    reason: str = ""

    def __post_init__(self):
        if not REGION.fullmatch(self.region) or not safe_pdf(self.pdf):
            raise ReviewError("invalid_reference", "Region and PDF must be plain names")
        if type(self.page) is not int or self.page < 1:
            raise ReviewError(
                "invalid_reference", "Page must be a positive one-based integer"
            )
        if not self.field_path.startswith("/"):
            raise ReviewError("invalid_reference", "field_path must be a JSON pointer")

    @property
    def card_id(self) -> str:
        return digest(json.dumps([self.region, self.pdf, self.page]).encode())

    @property
    def item_id(self) -> str:
        # Household indexes are checked at resolution but are not durable identity.
        logical = re.sub(r"/households/[0-9]+/", "/households/*/", self.field_path)
        return digest(json.dumps([self.card_id, logical]).encode())


@dataclass
class Resolved:
    record: dict
    field: dict
    label: str
    group: str
    household: dict
    record_index: int


def card_index(records: list[dict]) -> dict:
    """Physical card locations; duplicate owners remain detectable."""
    matches = {}
    for record_index, record in enumerate(records):
        for index, household in enumerate(record["dwelling"]["households"]):
            cards = [
                c for c in household.get("cards", []) if c["role"] == "coding-front"
            ]
            for card in cards:
                key = card["image"], card.get("page")
                matches.setdefault(key, []).append(
                    (record_index, index, cards[0] == card)
                )
    return matches


def resolve_field(records: list[dict], ref: Reference, locations=None) -> Resolved:
    locations = card_index(records) if locations is None else locations
    matches = locations.get((ref.pdf, ref.page), [])
    if len(matches) != 1:
        raise ReviewError(
            "ambiguous_card" if matches else "missing_card",
            "Physical coding card does not resolve uniquely",
            422 if matches else 404,
        )
    record_index, index, primary = matches[0]
    record = records[record_index]
    household = record["dwelling"]["households"][index]
    if not primary:
        raise ReviewError(
            "unsupported_source",
            "Only the household's first coding card owns its stored fields",
        )
    for label, (key, group) in FIELD_MAP.items():
        if group == "dwelling":
            pointer = f"/dwelling/{key}"
        elif group == "house":
            pointer = f"/dwelling/house/{key}"
        elif group == "household":
            pointer = f"/dwelling/households/{index}/{key}"
        else:
            pointer = f"/dwelling/households/{index}/{group}/{key}"
        if pointer != ref.field_path:
            continue
        if group in {"dwelling", "house"} and index != 0:
            raise ReviewError(
                "wrong_owner", "Shared fields belong to the first coding household"
            )
        node = record
        try:
            for part in pointer.split("/")[1:]:
                node = node[int(part)] if isinstance(node, list) else node[part]
        except (KeyError, IndexError, TypeError) as error:
            raise ReviewError(
                "stale_pointer", "The field is absent from its owning record"
            ) from error
        if node.get("source", "coding-front") != "coding-front":
            raise ReviewError(
                "unsupported_source", "Only C1/C2 numeric coding fields are supported"
            )
        return Resolved(record, node, label, group, household, record_index)
    raise ReviewError(
        "unsupported_field",
        "Unknown field, unsupported front field, or stale household pointer",
    )


@dataclass
class PreparedRegions:
    """Validated immutable candidates, prepared before acquiring the save lock."""

    regions: dict
    cards: dict
    audits: dict


def prepare_regions(regions: dict) -> PreparedRegions:
    # Each region has already passed parse_records/validate_records.
    validate_dataset(regions)
    return PreparedRegions(
        regions,
        {region: card_index(records) for region, (records, _) in regions.items()},
        {
            region: audit_index({region: records})
            for region, (records, _) in regions.items()
        },
    )


class RecordStore:
    """JSONL is authoritative; validated records and lookup/audit indexes are cached."""

    def __init__(self, directory: Path, *, load=True):
        self.directory = directory.resolve()
        self.lock = RLock()
        self.regions: dict[str, tuple[list[dict], str]] = {}
        self.cards = {}
        self.requests, self.decisions = {}, {}
        self.event_regions = {"request_id": {}, "id": {}}
        self.region_audits = {}
        if load:
            self.reload()

    def reload(self):
        candidate = prepare_regions(
            read_dataset(sorted(self.directory.glob("*.jsonl")))
        )
        with self.lock:
            self.regions.clear()
            self.cards.clear()
            self.requests.clear()
            self.decisions.clear()
            self.region_audits.clear()
            for owners in self.event_regions.values():
                owners.clear()
            self.install(candidate)

    def check_audits(self, candidate: PreparedRegions):
        for region, indexes in candidate.audits.items():
            for key, incoming, existing in zip(
                ("request_id", "id"), indexes, (self.requests, self.decisions)
            ):
                for identity in incoming:
                    owner = self.event_regions[key].get(identity)
                    if identity in existing and owner not in candidate.regions:
                        raise ReviewError(
                            "invalid_history",
                            f"Duplicate audit {key}: {owner}.jsonl and {region}.jsonl",
                        )

    def install(self, candidate: PreparedRegions):
        """Install checked regions atomically; unchanged regions/indexes are retained."""
        self.check_audits(candidate)
        # Remove all replaced ownership before installing any new ownership.
        for region in candidate.regions:
            for key, old, existing in zip(
                ("request_id", "id"),
                self.region_audits.get(region, ({}, {})),
                (self.requests, self.decisions),
            ):
                for identity in old:
                    existing.pop(identity, None)
                    self.event_regions[key].pop(identity, None)
        for region, indexes in candidate.audits.items():
            for key, new, existing in zip(
                ("request_id", "id"), indexes, (self.requests, self.decisions)
            ):
                existing.update(new)
                self.event_regions[key].update(dict.fromkeys(new, region))
            self.region_audits[region] = indexes
        self.regions.update(candidate.regions)
        self.cards.update(candidate.cards)

    def current(self, ref: Reference) -> tuple[Resolved, str]:
        try:
            records, version = self.regions[ref.region]
        except KeyError as error:
            raise ReviewError(
                "missing_region", f"No extracted records for {ref.region}", 404
            ) from error
        return resolve_field(records, ref, self.cards[ref.region]), version

    def check_version(self, region: str, expected: str) -> None:
        _, version = self.regions[region]
        if expected != version:
            raise ReviewError(
                "stale_version", "Region changed; reload before saving", 409
            )
        try:
            actual = digest((self.directory / f"{region}.jsonl").read_bytes())
        except OSError as error:
            raise ReviewError(
                "save_failed", "Region file is unavailable", 500
            ) from error
        if actual != version:
            raise ReviewError(
                "external_change",
                "An external writer changed this region; restart before saving",
                409,
            )

    def write(self, region: str, records: list[dict]) -> str:
        text = "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records)
        try:
            write_atomic(self.directory / f"{region}.jsonl", text)
        except OSError as error:
            raise ReviewError(
                "save_failed",
                "Could not replace region file; previous local data retained",
                500,
            ) from error
        return digest(text.encode("utf-8"))

    def save_record(self, region: str, expected: str, index: int, record: dict) -> str:
        """Validate one changed dwelling, retaining all other validated records."""
        with self.lock:
            self.check_version(region, expected)
            validate_records([record], region)
            records = list(self.regions[region][0])
            old = records[index]
            # Review cannot change card ownership; reruns/imports use full validation.
            if card_index([old]) != card_index([record]):
                raise ReviewError(
                    "wrong_owner", "Review cannot change physical card ownership"
                )
            incoming = audit_index({region: [record]})
            previous = audit_index({region: [old]})
            for key, new, old_index, existing in zip(
                ("request_id", "id"),
                incoming,
                previous,
                (self.requests, self.decisions),
            ):
                for identity in new:
                    if identity in existing and identity not in old_index:
                        raise ReviewError("invalid_history", f"Duplicate audit {key}")
            records[index] = record
            version = self.write(region, records)
            # Publish indexes only after the durable replacement succeeds.
            for key, new, old_index, existing, regional in zip(
                ("request_id", "id"),
                incoming,
                previous,
                (self.requests, self.decisions),
                self.region_audits[region],
            ):
                for identity in old_index:
                    existing.pop(identity, None)
                    regional.pop(identity, None)
                    self.event_regions[key].pop(identity, None)
                existing.update(new)
                regional.update(new)
                self.event_regions[key].update(dict.fromkeys(new, region))
            self.regions[region] = records, version
            return version

    def save(self, region: str, expected: str, records: list[dict]) -> str:
        """Full replacement/import path; ordinary decisions use save_record."""
        with self.lock:
            self.check_version(region, expected)
            validate_records(records, region)
            candidate = prepare_regions({region: (deepcopy(records), expected)})
            self.check_audits(candidate)
            version = self.write(region, candidate.regions[region][0])
            candidate.regions[region] = candidate.regions[region][0], version
            self.install(candidate)
            return version


def current_fields(node: Any, path: tuple = ()):
    """Visit live fields once; never descend into provenance or audit snapshots."""
    if isinstance(node, dict):
        if {"value", "status"} <= node.keys():
            yield path, node
            return
        children = node.items()
    elif isinstance(node, list):
        children = enumerate(node)
    else:
        return
    for key, child in children:
        yield from current_fields(child, (*path, key))

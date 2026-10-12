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
    return [
        f"{'/'.join(map(str, e.absolute_path)) or '<record>'}: {e.message}"
        for e in VALIDATOR.iter_errors(record)
    ]


def validate_records(records: list[dict], region: str) -> None:
    seen, decision_ids, request_ids = set(), set(), set()
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
            for event in field.get("review", {}).get("history", []):
                if event["id"] in decision_ids or event["request_id"] in request_ids:
                    raise ReviewError(
                        "invalid_history", "Duplicate audit decision or request ID"
                    )
                decision_ids.add(event["id"])
                request_ids.add(event["request_id"])
        for household in record["dwelling"]["households"]:
            for card in household.get("cards", []):
                if card["role"] != "coding-front":
                    continue
                key = card["image"], card.get("page")
                if key in seen:
                    raise ReviewError("ambiguous_card", f"duplicate coding card {key}")
                seen.add(key)


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


def read_records(path: Path, region: str) -> tuple[list[dict], str]:
    try:
        raw = path.read_bytes()
        records = [
            json.loads(line)
            for line in raw.decode("utf-8-sig").splitlines()
            if line.strip()
        ]
    except (OSError, ValueError, UnicodeError) as error:
        raise ReviewError(
            "invalid_records", f"Cannot read {path.name}: {error}"
        ) from error
    validate_records(records, region)
    return records, digest(raw)


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


def resolve_field(records: list[dict], ref: Reference) -> Resolved:
    matches = []
    for record in records:
        for index, household in enumerate(record["dwelling"]["households"]):
            cards = [
                c for c in household.get("cards", []) if c["role"] == "coding-front"
            ]
            for card in cards:
                if (card["image"], card.get("page")) == (ref.pdf, ref.page):
                    matches.append((record, index, household, cards[0] == card))
    if len(matches) != 1:
        raise ReviewError(
            "ambiguous_card" if matches else "missing_card",
            "Physical coding card does not resolve uniquely",
            422 if matches else 404,
        )
    record, index, household, primary = matches[0]
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
        return Resolved(record, node, label, group, household)
    raise ReviewError(
        "unsupported_field",
        "Unknown field, unsupported front field, or stale household pointer",
    )


class RecordStore:
    """In-memory region index; JSONL is the sole durable source of truth.

    Lookups never reread a batch. Mutations check its digest before replacing it.
    External writers are unsupported and require a restart/reload.
    """

    def __init__(self, directory: Path):
        self.directory = directory.resolve()
        self.lock = RLock()
        self.regions: dict[str, tuple[list[dict], str]] = {}
        self.reload()

    def reload(self):
        with self.lock:
            regions = {}
            for path in sorted(self.directory.glob("*.jsonl")):
                if not REGION.fullmatch(path.stem) or path.is_symlink():
                    raise ReviewError(
                        "invalid_path", f"Unsupported results path: {path.name}"
                    )
                regions[path.stem] = read_records(path, path.stem)
            self.regions = regions

    def current(self, ref: Reference) -> tuple[Resolved, str]:
        try:
            records, version = self.regions[ref.region]
        except KeyError as error:
            raise ReviewError(
                "missing_region", f"No extracted records for {ref.region}", 404
            ) from error
        return resolve_field(records, ref), version

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

    def save(self, region: str, expected: str, records: list[dict]) -> str:
        with self.lock:
            validate_records(records, region)
            self.check_version(region, expected)
            text = "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records)
            try:
                write_atomic(self.directory / f"{region}.jsonl", text)
            except OSError as error:
                raise ReviewError(
                    "save_failed",
                    "Could not replace region file; previous local data retained",
                    500,
                ) from error
            version = digest(text.encode("utf-8"))
            self.regions[region] = deepcopy(records), version
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

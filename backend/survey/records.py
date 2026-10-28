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
from survey.review.fields import descriptor

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


def physical_card_id(region: str, image: str, page: int | None) -> str:
    """Stable physical identity, including read-only cards without a page."""
    return digest(json.dumps([region, image, page]).encode())


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


def validate_records(
    records: list[dict], region: str, *, allow_duplicate_cards: bool = False
) -> None:
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
        for path, field in current_fields(record):
            logical = retained_field_path(path)
            validate_history(field, descriptor("/" + "/".join(map(str, logical))))
        for household in record["dwelling"]["households"]:
            for card in household.get("cards", []):
                if card["role"] != "coding-front":
                    continue
                key = card["image"], card.get("page")
                if key in seen and not allow_duplicate_cards:
                    raise ReviewError("ambiguous_card", f"duplicate coding card {key}")
                seen.add(key)
        if record["schema_version"] == "0.7.0":
            validate_prepared_record(record)
    if records and all(r["schema_version"] == "0.7.0" for r in records):
        from survey.review.relinking import duplicate_index, identity, owner

        duplicates = {
            c for members in duplicate_index(records).values() for c in members
        }
        for record in records:
            for h in record["dwelling"]["households"]:
                flags = h.get("flags", [])
                if h["record_id"] != identity(h) or (
                    ("duplicate_record_id" in flags) != (owner(region, h) in duplicates)
                ):
                    raise ReviewError(
                        "invalid_records",
                        "Derived identity or duplicate flags disagree with physical card readings",
                    )
        sources, bundle_ids = set(), set()
        for record in records:
            for h in record["dwelling"]["households"]:
                active = list(h.get("cards", []))
                for bundle in h.get("retained_supplements", []):
                    if bundle["id"] in bundle_ids or bundle["source_members"] != [
                        owner(region, h)
                    ]:
                        raise ReviewError(
                            "invalid_records",
                            "Retained evidence has duplicate identity or an invalid custodian",
                        )
                    bundle_ids.add(bundle["id"])
                    active.extend(bundle["payload"].get("cards", []))
                for c in active:
                    key = c["image"], c.get("page")
                    if key in sources and not allow_duplicate_cards:
                        raise ReviewError(
                            "ambiguous_card",
                            f"Physical source {key} occurs more than once in active or retained evidence",
                        )
                    sources.add(key)
            for c in record["dwelling"].get("cards", []):
                key = c["image"], c.get("page")
                if key in sources:
                    raise ReviewError(
                        "ambiguous_card",
                        f"Supplementary source {key} occurs more than once",
                    )
                sources.add(key)
    audit_index({region: records})


def retained_field_path(path):
    """Retained payloads keep their original front/note field semantics."""
    if "retained_supplements" in path and "payload" in path:
        return ("dwelling", *path[path.index("payload") + 1 :])
    return path


def validate_prepared_record(record):
    from survey.review.relinking import coding_source

    pdfs = set()
    for h in record["dwelling"]["households"]:
        card = coding_source(h)
        pdfs.add(card["image"])
        if (
            not safe_pdf(card["image"])
            or type(card.get("page")) is not int
            or card["page"] < 1
        ):
            raise ReviewError(
                "invalid_records",
                "Coding sources require a PDF basename and original page",
            )
        active = []
        for event in h.get("link_history", []):
            if event["card_id"] != physical_card_id(
                record["region"], card["image"], card["page"]
            ):
                raise ReviewError(
                    "invalid_history",
                    "Link history belongs to a different physical card",
                )
            if event["request"]["action"] != event["action"]:
                raise ReviewError("invalid_history", "Link event and request disagree")
            if event["action"] == "undo":
                if (
                    not active
                    or active[-1]["id"] != event.get("undo_target")
                    or event["request"]["undo_target"] != event["undo_target"]
                ):
                    raise ReviewError(
                        "invalid_history",
                        "Link Undo must reverse its latest applicable operation",
                    )
                active.pop()
            else:
                if "structure" not in event:
                    raise ReviewError(
                        "invalid_history",
                        "Link event has no reversible structural effect",
                    )
                active.append(event)
    for card in record["dwelling"].get("cards", []):
        if card["role"] not in {"survey-front", "survey-back"}:
            raise ReviewError(
                "invalid_records",
                "Active dwelling evidence must be a survey front or back",
            )
        pdfs.add(card["image"])
    if len(pdfs) != 1:
        raise ReviewError(
            "wrong_boundary", "A prepared dwelling must stay within one PDF"
        )


def audit_index(regions: dict[str, list[dict]]) -> tuple[dict, dict]:
    """Build one dataset-wide registry, reporting both duplicate locations."""
    requests, decisions, locations = {}, {}, {}
    for region, records in regions.items():
        for number, record in enumerate(records, 1):
            entries = []
            for path, field in current_fields(record):
                location = f"{region}.jsonl record {number} /{'/'.join(map(str, path))}"
                for event in field.get("review", {}).get("history", []):
                    entries.append((location, event))
            for h in record["dwelling"]["households"]:
                entries.extend(
                    (f"{region}.jsonl record {number} link history", e)
                    for e in h.get("link_history", [])
                )
            for location, event in entries:
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


def validate_history(field: dict, spec=None) -> None:
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
                    valid = (
                        spec.valid_correction(value)
                        if spec
                        else (
                            isinstance(value, str)
                            and bool(re.fullmatch(r"[0-9]{1,64}", value))
                        )
                    )
                    if not valid:
                        raise ReviewError(
                            "invalid_history",
                            "Correction request must satisfy its established field type",
                        )
                    expected_payload.update(value=value, status="ok")
                    # Decoding is field-specific; validate the preserved envelope
                    # here without imposing a closed field set on old records.
                    for key in ("code", "label"):
                        if (
                            spec
                            and spec.spec.kind == "text"
                            and after.get(key) is not None
                        ):
                            raise ReviewError(
                                "invalid_history",
                                "Text corrections cannot introduce codebook values",
                            )
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


def parse_records(
    raw: bytes, region: str, name: str, *, allow_duplicate_cards: bool = False
) -> tuple[list[dict], str]:
    try:
        records = [
            json.loads(line)
            for line in raw.decode("utf-8-sig").splitlines()
            if line.strip()
        ]
    except (ValueError, UnicodeError) as error:
        raise ReviewError("invalid_records", f"Cannot read {name}: {error}") from error
    validate_records(records, region, allow_duplicate_cards=allow_duplicate_cards)
    return records, digest(raw)


def read_records(
    path: Path, region: str, *, allow_duplicate_cards: bool = False
) -> tuple[list[dict], str]:
    try:
        raw = path.read_bytes()
    except OSError as error:
        raise ReviewError(
            "invalid_records", f"Cannot read {path.name}: {error}"
        ) from error
    return parse_records(
        raw, region, path.name, allow_duplicate_cards=allow_duplicate_cards
    )


def validate_dataset(regions: dict[str, tuple[list[dict], str]]) -> None:
    """Check cross-file constraints after parse_records validated each file."""
    if not regions:
        raise ReviewError("missing_records", "No region JSONL found")
    for region, (records, _) in regions.items():
        if not records:
            raise ReviewError("empty_records", f"{region}.jsonl contains no records")
    audit_index({region: records for region, (records, _) in regions.items()})


def read_dataset(
    paths: list[Path], *, allow_duplicate_cards: bool = False
) -> dict[str, tuple[list[dict], str]]:
    """Read validated regions. Queue generation may retain duplicate cards so
    it can report and skip them; schema and review-history checks still apply.
    Review loading and persistence reject duplicates by default.
    """
    candidate = {}
    for path in paths:
        if not REGION.fullmatch(path.stem) or path.is_symlink():
            raise ReviewError(
                "invalid_path", f"Unsupported region JSONL path: {path.name}"
            )
        if path.stem in candidate:
            raise ReviewError("invalid_path", f"Duplicate region file: {path.name}")
        candidate[path.stem] = read_records(
            path, path.stem, allow_duplicate_cards=allow_duplicate_cards
        )
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
    # Internal binding, obtained only after checking IT-89's physical ownership.
    front_page: int | None = None

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
        return physical_card_id(self.region, self.pdf, self.page)

    @property
    def item_id(self) -> str:
        # Household indexes are checked at resolution but are not durable identity.
        logical = re.sub(r"/households/[0-9]+/", "/households/*/", self.field_path)
        if self.front_page is not None:
            logical = f"/dwelling/notes/front/{self.front_page}/text"
        return digest(json.dumps([self.card_id, logical]).encode())


@dataclass
class Resolved:
    record: dict
    field: dict
    label: str
    group: str
    household: dict
    record_index: int
    descriptor: Any = None
    front_page: int | None = None


def card_index(records: list[dict]) -> dict:
    """Physical card locations; duplicate owners remain detectable."""
    matches = {}
    for record_index, record in enumerate(records):
        for card in record["dwelling"].get("cards", []):
            if card["role"] in {"survey-front", "survey-back"}:
                key = card["image"], card.get("page")
                matches.setdefault(key, []).append((record_index, None, card["role"]))
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


def field_pointer(key: str, group: str, index: int, *, shared=False) -> str:
    """The JSON pointer to a FIELD_MAP field on household ``index``.

    Each card owns its fields (0.7.0); ``shared`` gives the 0.6.0 pointer,
    where dwelling and house fields sit once on the dwelling.
    """
    if shared and group == "dwelling":
        return f"/dwelling/{key}"
    if shared and group == "house":
        return f"/dwelling/house/{key}"
    if group in {"dwelling", "household"}:
        return f"/dwelling/households/{index}/{key}"
    return f"/dwelling/households/{index}/{group}/{key}"


def resolve_field(records: list[dict], ref: Reference, locations=None) -> Resolved:
    locations = card_index(records) if locations is None else locations
    matches = locations.get((ref.pdf, ref.page), [])
    if len(matches) != 1:
        raise ReviewError(
            "ambiguous_card" if matches else "missing_card",
            "Physical card does not resolve uniquely",
            422 if matches else 404,
        )
    record_index, index, primary = matches[0]
    record = records[record_index]
    spec = descriptor(ref.field_path)
    if index is None:
        return resolve_front_field(record, ref, record_index, primary, spec, locations)
    household = record["dwelling"]["households"][index]
    if not primary:
        raise ReviewError(
            "unsupported_source",
            "Only the household's first coding card owns its stored fields",
        )
    if record["schema_version"] == "0.7.0":
        if spec is None or spec.role != "coding-front":
            raise ReviewError("unsupported_field", "Unknown coding-card field")
        label = spec.spec.name
        key, group = FIELD_MAP[label]
        suffix = (
            f"house/{key}"
            if group == "house"
            else key
            if group in {"dwelling", "household"}
            else f"{group}/{key}"
        )
        pointer = f"/dwelling/households/{index}/{suffix}"
        logical = re.sub(r"/households/[0-9]+/", "/households/*/", ref.field_path)
        if logical != re.sub(r"/households/[0-9]+/", "/households/*/", pointer):
            raise ReviewError(
                "unsupported_field", "Prepared fields require per-card ownership"
            )
        node = record
        try:
            for part in pointer.split("/")[1:]:
                node = node[int(part)] if isinstance(node, list) else node[part]
        except (KeyError, IndexError, TypeError) as error:
            raise ReviewError(
                "stale_pointer", "The card's own field is absent"
            ) from error
        if node.get("source", "coding-front") != "coding-front":
            raise ReviewError(
                "unsupported_source", "Coding fields require their own coding source"
            )
        return Resolved(
            record,
            node,
            label,
            "household" if group == "dwelling" else group,
            household,
            record_index,
            descriptor(pointer),
        )
    if ref.field_path == f"/dwelling/households/{index}/municipality":
        if "municipality" not in household:
            raise ReviewError("stale_pointer", "Legacy household has no municipality")
        return Resolved(
            record,
            household["municipality"],
            "Municipality",
            "household",
            household,
            record_index,
            spec,
        )
    for label, (key, group) in FIELD_MAP.items():
        pointer = field_pointer(key, group, index, shared=True)
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
        return Resolved(record, node, label, group, household, record_index, spec)
    raise ReviewError(
        "unsupported_field",
        "Unknown field, unsupported front field, or stale household pointer",
    )


def resolve_front_field(record, ref, record_index, role, spec, locations):
    if spec is None or spec.role != role:
        raise ReviewError(
            "unsupported_field",
            "Field does not resolve uniquely to this source; person columns lack physical provenance",
        )
    dwelling = record["dwelling"]
    cards = dwelling.get("cards", [])
    fronts = [card for card in cards if card["role"] == "survey-front"]
    try:
        node = record
        for part in ref.field_path.split("/")[1:]:
            node = node[int(part)] if isinstance(node, list) else node[part]
    except (KeyError, IndexError, TypeError) as error:
        raise ReviewError(
            "stale_pointer", "The field is absent from its owning record"
        ) from error
    if not isinstance(node, dict) or node.get("source") != role:
        raise ReviewError(
            "unsupported_source", "Field source must match the verified physical card"
        )
    front_page = None
    if role == "survey-front":
        if len(fronts) != 1 or (fronts[0]["image"], fronts[0].get("page")) != (
            ref.pdf,
            ref.page,
        ):
            raise ReviewError(
                "ambiguous_source",
                "Multiple fronts can contribute to this field; exact ownership is unresolved",
            )
        if any(
            event["item_id"] != ref.item_id
            for event in node.get("review", {}).get("history", [])
        ):
            raise ReviewError(
                "changed_source",
                "Reviewed front's physical ownership changed; reconcile explicitly",
            )
    else:
        note = dwelling["notes"][int(ref.field_path.split("/")[3])]
        front_page = note["front_page"]
        if ref.front_page is not None and ref.front_page != front_page:
            raise ReviewError(
                "stale_pointer",
                "Note order changed; reload the supplied queue with verified pointers",
            )
        owners = [card for card in fronts if card.get("page") == front_page]
        if (
            len(owners) != 1
            or owners[0]["image"] != ref.pdf
            or note.get("page") != ref.page
        ):
            raise ReviewError(
                "ambiguous_source",
                "Note requires an unambiguous front and matching original back",
            )
        front = owners[0]
        if len(locations.get((ref.pdf, front_page), [])) != 1:
            raise ReviewError(
                "ambiguous_source", "Note's front does not resolve uniquely"
            )
        at = cards.index(front)
        if (
            at + 1 >= len(cards)
            or cards[at + 1].get("role") != "survey-back"
            or (cards[at + 1]["image"], cards[at + 1].get("page"))
            != (ref.pdf, ref.page)
        ):
            raise ReviewError(
                "ambiguous_source",
                "Note's stored front/back association changed or is missing",
            )
        if (
            sum(
                note["front_page"] == n["front_page"] for n in dwelling.get("notes", [])
            )
            != 1
        ):
            raise ReviewError("ambiguous_source", "Several notes claim the same front")
        bound = Reference(
            ref.region, ref.pdf, ref.page, ref.field_path, front_page=front_page
        )
        history = node.get("review", {}).get("history", [])
        if history and any(event["item_id"] != bound.item_id for event in history):
            raise ReviewError(
                "changed_source",
                "Reviewed note's physical association changed; reconcile explicitly",
            )
    return Resolved(
        record,
        node,
        spec.spec.name,
        spec.group,
        dwelling["households"][0],
        record_index,
        spec,
        front_page,
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
        children = (
            (k, v) for k, v in node.items() if k not in {"link_history", "structure"}
        )
    elif isinstance(node, list):
        children = enumerate(node)
    else:
        return
    for key, child in children:
        yield from current_fields(child, (*path, key))

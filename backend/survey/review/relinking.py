"""Pure per-card identity, membership planning and reversible structural effects.

No extraction, scoring, disk I/O or review policy lives here. Retained evidence
is deliberately separate from the active dwelling's supplementary fields.
"""

import json
from collections import Counter, defaultdict
from copy import deepcopy

from survey.extraction.record import SCHEMA_VERSION, build_record_id
from survey.records import ReviewError, digest, physical_card_id

REVIEW_SCHEMA = SCHEMA_VERSION
# What finish_records gives a card with no survey front.
UNFRONTED = {
    "state": "provisional",
    "reason": "This card has no associated survey front",
}
# Per-household identity flags refresh_identities recomputes from scratch.
DERIVED_IDENTITY_FLAGS = {
    "duplicate_record_id",
    "incomplete_identity",
    "municipality_mismatch",
    "dwelling_number_mismatch",
}
SUPPLEMENT_KEYS = {"address", "families_in_dwelling", "handwritten", "notes", "cards"}


def canonical_hash(value):
    return digest(json.dumps(value, sort_keys=True, ensure_ascii=False).encode())


def coding_source(household):
    cards = [c for c in household.get("cards", []) if c["role"] == "coding-front"]
    if len(cards) != 1:
        raise ReviewError(
            "ambiguous_card", "Each review household needs one coding source"
        )
    return cards[0]


def owner(region, household):
    c = coding_source(household)
    return physical_card_id(region, c["image"], c.get("page"))


def identity(household):
    try:
        return build_record_id(
            *(
                household[k].get("value") or ""
                for k in ("municipality", "dwelling_no", "household_no")
            )
        )
    except ValueError:
        return None


def dwelling_key(household):
    # A missing household number does not prevent matching a dwelling.
    try:
        return build_record_id(
            household["municipality"].get("value") or "",
            household["dwelling_no"].get("value") or "",
            "1",
        )[:-3]
    except ValueError:
        return None


def inventory(records):
    return {
        owner(r["region"], h): (ri, hi, r, h)
        for ri, r in enumerate(records)
        for hi, h in enumerate(r["dwelling"]["households"])
    }


def duplicate_index(records):
    groups = defaultdict(list)
    for r in records:
        for h in r["dwelling"]["households"]:
            if value := identity(h):
                groups[(r["region"], coding_source(h)["image"], value)].append(
                    owner(r["region"], h)
                )
    return {key: sorted(members) for key, members in groups.items() if len(members) > 1}


def conflicts(records, card_id, duplicates=None):
    return next(
        (
            {"identity": key[2], "card_ids": members}
            for key, members in (
                duplicate_index(records) if duplicates is None else duplicates
            ).items()
            if card_id in members
        ),
        None,
    )


def refresh_identities(records):
    """Recompute derived IDs and current flags, without touching extraction notes."""
    duplicates = {c for ids in duplicate_index(records).values() for c in ids}
    for r in records:
        hs = r["dwelling"]["households"]
        by_owner = {owner(r["region"], h): h for h in hs}
        municipalities = {
            h["municipality"].get("value", "").lstrip("0") or "0"
            for h in hs
            if h["municipality"].get("value") is not None
        }
        numbers = {dwelling_key(h) for h in hs if dwelling_key(h) is not None}
        front = front_number(r["dwelling"])
        for h in hs:
            h["record_id"] = identity(h)
            flags = set(h.get("flags", [])) - DERIVED_IDENTITY_FLAGS
            if h["record_id"] is None:
                flags.add("incomplete_identity")
            if owner(r["region"], h) in duplicates:
                flags.add("duplicate_record_id")
            if len(municipalities) > 1:
                flags.add("municipality_mismatch")
            key = dwelling_key(h)
            if len({k.split("-")[1] for k in numbers}) > 1 or (
                front and key and key.split("-")[1] != front
            ):
                flags.add("dwelling_number_mismatch")
            h["flags"] = sorted(flags)
        for note in r["dwelling"].get("notes", []):
            if linked := note.get("household_card_id"):
                note["household_id"] = (
                    by_owner[linked]["record_id"] if linked in by_owner else None
                )


def finish_records(records):
    """Give per-card records their derived review state (schema 0.7.0).

    A card with no survey front is provisional, a note's ``household_id``
    resolves to its card within its own group, and IDs and identity flags are
    recomputed. Shared by the pipeline and preparation, so both write the same.
    """
    for r in records:
        d = r["dwelling"]
        fronted = any(c["role"] == "survey-front" for c in d.get("cards", []))
        for h in d["households"]:
            if not fronted and "relink" not in h:
                h["relink"] = deepcopy(UNFRONTED)
        for note in d.get("notes", []):
            if note.get("household_card_id") or note.get("household_id") is None:
                continue
            matches = [
                h for h in d["households"] if h["record_id"] == note["household_id"]
            ]
            if len(matches) == 1:
                note["household_card_id"] = owner(r["region"], matches[0])
    refresh_identities(records)
    for r in records:
        d = r["dwelling"]
        # Legacy dwelling-level identity flags; each card now carries its own.
        flags = set(d.pop("flags", [])) - {"duplicate_record_id", "missing_record_id"}
        if any(h["record_id"] is None for h in d["households"]):
            flags.add("missing_record_id")
        if flags:
            d["flags"] = sorted(flags)
    return records


def front_number(dwelling):
    raw = dwelling.get("handwritten", {}).get("dwelling_no", {})
    if raw.get("status") != "ok":
        return None
    try:
        return build_record_id("1", raw["value"], "1").split("-")[1]
    except ValueError:
        return None


def has_supplements(record):
    d = record["dwelling"]
    return any(d.get(k) for k in SUPPLEMENT_KEYS) or any(
        h.get("persons") for h in d["households"]
    )


def owned_notes(record, h):
    cid = owner(record["region"], h)
    return any(
        n.get("household_card_id") == cid for n in record["dwelling"].get("notes", [])
    )


def assert_conservation(before, after):
    """Every API transaction preserves physical sources and person rows once."""

    def contents(records):
        cards, persons = Counter(), Counter()
        for r in records:
            for c in r["dwelling"].get("cards", []):
                cards[r["region"], c["role"], c["image"], c.get("page")] += 1
            for h in r["dwelling"]["households"]:
                for c in h.get("cards", []):
                    cards[r["region"], c["role"], c["image"], c.get("page")] += 1
                persons.update(canonical_hash(p) for p in h.get("persons", []))
                for bundle in h.get("retained_supplements", []):
                    for c in bundle["payload"].get("cards", []):
                        cards[r["region"], c["role"], c["image"], c.get("page")] += 1
                    persons.update(
                        canonical_hash(p) for p in bundle["payload"].get("persons", [])
                    )
        return cards, persons

    if contents(before) != contents(after):
        raise ReviewError(
            "preservation_conflict",
            "The operation would lose or duplicate a physical source or person row",
            409,
        )


def group_candidate(record, key, pdf, *, current=False):
    hs = record["dwelling"]["households"]
    if any(coding_source(h)["image"] != pdf for h in hs):
        return None
    keys = {dwelling_key(h) for h in hs}
    if key not in keys:
        return None
    d = record["dwelling"]
    fronts = [c for c in d.get("cards", []) if c["role"] == "survey-front"]
    number = front_number(d)
    number_matches = number == key.split("-")[1]
    clear = (
        keys == {key}
        and bool(fronts)
        and number_matches
        and "fronts_disagree" not in d.get("flags", [])
        and all(c["image"] == pdf for c in d.get("cards", []))
    )
    return {
        "card_id": owner(record["region"], hs[0]),
        "clear": clear,
        "current": current,
        "front_pages": [c["page"] for c in fronts],
        "coding_pages": [coding_source(h)["page"] for h in hs],
        "address": d.get("address", {}).get("value"),
        "reason": "Compatible front and coding readings"
        if clear
        else "Coding-only, missing front number, or conflicting group evidence",
    }


def current_fits(record, h, key):
    """Keep an existing association unless its other evidence contradicts it.

    Unknown readings do not contradict. The edited card alone does not
    corroborate its own group: a sole coding-only card has nothing to keep.
    """
    d = record["dwelling"]
    known = {dwelling_key(o) for o in d["households"] if o is not h} - {None}
    number = front_number(d)
    if (
        known - {key}
        or (number and number != key.split("-")[1])
        or "fronts_disagree" in d.get("flags", [])
    ):
        return False
    return len(d["households"]) > 1 or any(
        c["role"] == "survey-front" for c in d.get("cards", [])
    )


def partly_fits(record, h, key):
    """A sibling card or the front still reads this card's dwelling."""
    d = record["dwelling"]
    return key in {dwelling_key(o) for o in d["households"] if o is not h} or (
        front_number(d) == key.split("-")[1]
    )


def plan_membership(records, card_id, inv=None):
    ri, _, record, h = (inv or inventory(records))[card_id]
    key, pdf = dwelling_key(h), coding_source(h)["image"]
    candidates = []
    if key:
        for i, r in enumerate(records):
            c = group_candidate(r, key, pdf, current=i == ri)
            if c:
                candidates.append(c)
    others = [c for c in candidates if not c["current"]]
    if key and current_fits(record, h, key):
        # The existing association competes with any other compatible group.
        outcome, target = ("ambiguous" if others else "unchanged"), None
    elif (
        (key and partly_fits(record, h, key))
        or len(others) > 1
        or (others and not others[0]["clear"])
    ):
        # Mixed evidence that still backs this group is a reviewer's choice,
        # never an automatic split.
        outcome, target = "ambiguous", None
    elif others:
        outcome, target = "clear", others[0]["card_id"]
    elif not key:
        outcome, target = "incomplete", None
    elif len(record["dwelling"]["households"]) == 1 and not has_supplements(record):
        outcome, target = "provisional", None
    else:
        outcome, target = "unmatched", None
    if outcome in {"clear", "unmatched"}:
        hs = record["dwelling"]["households"]
        if len(hs) == 1 and has_supplements(record):
            outcome = "supplementary_pending"
        elif h.get("persons"):
            outcome = "persons_pending"
        elif owned_notes(record, h):
            outcome = "notes_pending"
    return {"outcome": outcome, "target_card_id": target, "candidates": candidates}


def topology(record):
    d = record["dwelling"]
    return {
        "cards": [[c["role"], c["image"], c.get("page")] for c in d.get("cards", [])],
        "notes": sorted(
            [n["front_page"], n.get("page"), n.get("household_card_id") or ""]
            for n in d.get("notes", [])
        ),
        "keys": sorted(k for k in SUPPLEMENT_KEYS if d.get(k)),
        "persons": {
            owner(record["region"], h): canonical_hash(h["persons"])
            for h in d["households"]
            if h.get("persons")
        },
    }


def frame(record):
    return {
        "members": [
            owner(record["region"], h) for h in record["dwelling"]["households"]
        ],
        "envelope": {k: deepcopy(v) for k, v in record.items() if k != "dwelling"},
        "flags": deepcopy(record["dwelling"].get("flags", [])),
        "topology": topology(record),
        # Each member's dwelling identity, so Undo sees a later edit to any of them.
        "keys": {
            owner(record["region"], h): dwelling_key(h)
            for h in record["dwelling"]["households"]
        },
    }


def move(records, card_id, target_id, operation_id, *, retain=False):
    """Move live household data once; snapshots contain topology, never histories."""
    inv = inventory(records)
    _, _, source, h = inv[card_id]
    target = inv[target_id][2] if target_id else None
    if target is source:
        raise ReviewError("no_op", "This card is already in that dwelling")
    if target and (
        target["region"] != source["region"]
        or coding_source(inv[target_id][3])["image"] != coding_source(h)["image"]
    ):
        raise ReviewError(
            "wrong_boundary", "Linking must stay in the same region and PDF"
        )
    before = [frame(source)] + ([frame(target)] if target else [])
    effect = {
        "operation_id": operation_id,
        "previous_link_id": latest_link_id(h),
        "card_id": card_id,
        "identity_key": dwelling_key(h),
        "before": before,
        "previous_relink": deepcopy(h.get("relink")),
        "bundle_id": None,
    }
    if len(source["dwelling"]["households"]) == 1 and has_supplements(source):
        if not retain:
            raise ReviewError(
                "supplementary_pending",
                "Confirm retention of the former dwelling's evidence",
                409,
            )
        payload = {
            k: deepcopy(source["dwelling"][k])
            for k in SUPPLEMENT_KEYS | {"flags"}
            if k in source["dwelling"]
        }
        payload["persons"] = h.pop("persons", [])
        bundle = {
            "id": operation_id,
            "source_members": before[0]["members"],
            "payload": payload,
        }
        h.setdefault("retained_supplements", []).append(bundle)
        effect["bundle_id"] = bundle["id"]
        effect["bundle_hash"] = canonical_hash(bundle)
    elif owned_notes(source, h):
        raise ReviewError(
            "notes_pending",
            "A source note explicitly belongs to this card; settle supplementary ownership before moving",
            409,
        )
    elif h.get("persons"):
        raise ReviewError(
            "persons_pending",
            "Person ownership must be settled before moving this card",
            409,
        )
    source["dwelling"]["households"].remove(h)
    if target is None:
        target = {**deepcopy(before[0]["envelope"]), "dwelling": {"households": []}}
        records.append(target)
    target["dwelling"]["households"].append(h)
    if not source["dwelling"]["households"]:
        records.remove(source)
        # The reread warning would otherwise survive only in the audit frame.
        flags = target["dwelling"].get("flags", [])
        if "identity_reread" in source["dwelling"].get("flags", []) and (
            "identity_reread" not in flags
        ):
            target["dwelling"]["flags"] = sorted([*flags, "identity_reread"])
    effect["after"] = ([frame(source)] if source in records else []) + [frame(target)]
    return effect


def active_links(h):
    active = []
    for event in h.get("link_history", []):
        if event["action"] == "undo":
            active.pop()
        else:
            active.append(event)
    return active


def latest_link_id(h):
    active = active_links(h)
    return active[-1]["id"] if active else None


def restore_relink(h, value):
    if value is None:
        h.pop("relink", None)
    else:
        h["relink"] = deepcopy(value)


def undo_move(records, effect):
    before_members = [c for f in effect["before"] for c in f["members"]]
    after_members = [c for f in effect["after"] for c in f["members"]]
    if (
        Counter(before_members) != Counter(after_members)
        or effect["card_id"] not in before_members
        or len(before_members) != len(set(before_members))
    ):
        raise ReviewError(
            "undo_conflict",
            "The structural history does not preserve physical membership",
            409,
        )
    inv = inventory(records)
    card_id = effect["card_id"]
    if card_id not in inv or dwelling_key(inv[card_id][3]) != effect["identity_key"]:
        raise ReviewError(
            "undo_conflict",
            "The moved card's municipality or dwelling changed; undo that dependency first",
            409,
        )
    affected = []
    for expected in effect["after"]:
        entry = inv.get(expected["members"][0])
        if not entry:
            raise ReviewError(
                "undo_conflict", "An affected coding card is missing", 409
            )
        r = entry[2]
        actual = frame(r)
        if (
            set(actual["members"]) != set(expected["members"])
            or canonical_hash(actual["topology"])
            != canonical_hash(expected["topology"])
            or actual["envelope"] != expected["envelope"]
        ):
            raise ReviewError(
                "undo_conflict",
                "Affected dwelling membership or supplementary ownership changed; undo that dependency first",
                409,
            )
        if actual["keys"] != expected["keys"]:
            raise ReviewError(
                "undo_conflict",
                "A card in an affected dwelling changed its municipality or dwelling; undo that dependency first",
                409,
            )
        affected.append(r)
    h = inv[card_id][3]
    if latest_link_id(h) not in {effect["operation_id"], effect["previous_link_id"]}:
        raise ReviewError(
            "undo_conflict",
            "A later link decision applies to this card; undo that dependency first",
            409,
        )
    bundle = None
    if effect.get("bundle_id"):
        bundles = [
            b
            for b in h.get("retained_supplements", [])
            if b["id"] == effect["bundle_id"]
        ]
        if len(bundles) != 1 or canonical_hash(bundles[0]) != effect["bundle_hash"]:
            raise ReviewError(
                "undo_conflict",
                "The retained evidence bundle is missing or changed",
                409,
            )
        bundle = bundles[0]
    rebuilt = []
    for before in effect["before"]:
        members = before["members"]
        # Use the surviving group's current fields so unrelated edits survive.
        survivors = [c for c in members if c != card_id]
        if survivors:
            extras = deepcopy(
                {
                    k: v
                    for k, v in inv[survivors[0]][2]["dwelling"].items()
                    if k != "households"
                }
            )
            # Drop a flag this move carried in from the removed source.
            if before["flags"]:
                extras["flags"] = deepcopy(before["flags"])
            else:
                extras.pop("flags", None)
        elif bundle:
            extras = deepcopy(
                {k: v for k, v in bundle["payload"].items() if k != "persons"}
            )
            if bundle["payload"].get("persons"):
                h["persons"] = deepcopy(bundle["payload"]["persons"])
        else:
            extras = {"flags": deepcopy(before["flags"])} if before["flags"] else {}
        rebuilt.append(
            {
                **deepcopy(before["envelope"]),
                "dwelling": {**extras, "households": [inv[c][3] for c in members]},
            }
        )
    if bundle:
        h["retained_supplements"].remove(bundle)
        if not h["retained_supplements"]:
            h.pop("retained_supplements")
    restore_relink(h, effect["previous_relink"])
    at = min(records.index(r) for r in affected)
    records[:] = [r for r in records if not any(r is a for a in affected)]
    records[at:at] = rebuilt

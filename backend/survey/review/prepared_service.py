"""Review-schema operations using the existing regional store and field audit.

Legacy extraction validation remains in the shared modules. The HTTP reviewer
requires prepared data; these operations never guess missing per-card readings.
"""

import re
from copy import deepcopy
from dataclasses import replace
from datetime import UTC, datetime
from uuid import uuid4

from survey.records import Reference, ReviewError, physical_card_id, resolve_field
from survey.review import relinking as model
from survey.review.fields import field_pointers
from survey.review.service import (
    active_decisions,
    credentials,
    field_after,
    snapshot,
    state,
)


def rebind_reference(service, ref):
    records = service.store.regions.get(ref.region, ([], None))[0]
    if not records or records[0]["schema_version"] != model.REVIEW_SCHEMA:
        return ref
    owners = service.store.cards[ref.region].get((ref.pdf, ref.page), [])
    if len(owners) == 1:
        ri, hi, _ = owners[0]
        if hi is not None:
            return replace(
                ref,
                field_path=re.sub(
                    r"/households/[0-9]+/", f"/households/{hi}/", ref.field_path
                ),
            )
        if ref.front_page is not None or ref.field_path.startswith("/dwelling/notes/"):
            notes = records[ri]["dwelling"].get("notes", [])
            matches = [
                i
                for i, n in enumerate(notes)
                if n.get("page") == ref.page
                and (ref.front_page is None or n["front_page"] == ref.front_page)
            ]
            if len(matches) == 1:
                return replace(
                    ref,
                    field_path=f"/dwelling/notes/{matches[0]}/text",
                    front_page=notes[matches[0]]["front_page"],
                )
        return ref
    for record in records:
        for h in record["dwelling"]["households"]:
            for bundle in h.get("retained_supplements", []):
                if any(
                    (c["image"], c.get("page")) == (ref.pdf, ref.page)
                    for c in bundle["payload"].get("cards", [])
                ):
                    return None
    return ref


def refresh_regions(service, regions):
    """Rebind only changed assignments; unrelated progress/indexes stay cached."""
    regions = set(regions)
    valid = {
        key: ref for key, ref in service.references.items() if ref.region not in regions
    }
    errors = [d for d in service.diagnostics if d.get("region") not in regions]
    errors.extend(
        deepcopy(d)
        for d in service.assignment_diagnostics
        if d.get("region") in regions
    )
    for original in service.assignment_references:
        if original.region not in regions:
            continue
        ref = original
        try:
            ref = rebind_reference(service, original)
            if ref is None:
                continue
            resolved, _ = service.store.current(ref)
            if resolved.front_page is not None:
                ref = replace(ref, front_page=resolved.front_page)
            valid[ref.item_id] = ref
        except ReviewError as error:
            errors.append(
                {
                    "item_id": original.item_id,
                    "region": original.region,
                    "batch": original.pdf,
                    "page": original.page,
                    "field_path": original.field_path,
                    "code": error.code,
                    "message": str(error),
                }
            )
    # Preserve assignment order even when membership-derived array indexes move.
    ordered = {
        r.item_id: valid[r.item_id]
        for r in service.assignment_references
        if r.item_id in valid
    }
    ordered.update(valid)
    service.references, service.diagnostics = ordered, errors
    for region in regions:
        old_ids = {r.item_id for r in service.region_references.get(region, [])}
        for key in old_ids:
            service.item_resolved.pop(key, None)
        service.region_references[region] = [
            r for r in ordered.values() if r.region == region
        ]
    service.diagnostic_counts = {}
    for d in errors:
        key = d.get("region"), d.get("batch")
        service.diagnostic_counts[key] = service.diagnostic_counts.get(key, 0) + 1
    build_card_registry(service, regions)
    service.rebuild_progress(regions)


def build_card_registry(service, regions=None):
    if regions is None:
        service.card_registry, service.voluntary_references = {}, {}
        service.voluntary_by_card, service.prepared_indexes = {}, {}
    else:
        for cid, c in list(service.card_registry.items()):
            if c["region"] in regions:
                service.card_registry.pop(cid)
                service.voluntary_by_card.pop(cid, None)
        for key, ref in list(service.voluntary_references.items()):
            if ref.region in regions:
                service.voluntary_references.pop(key)
        for region in regions:
            service.prepared_indexes.pop(region, None)
    for region, (records, _) in service.store.regions.items():
        if regions is not None and region not in regions:
            continue
        for r in records:
            d = r["dwelling"]
            for hi, h in enumerate(d["households"]):
                for c in h.get("cards", []):
                    cid = physical_card_id(region, c["image"], c.get("page"))
                    service.card_registry[cid] = {
                        **c,
                        "region": region,
                        "retained": False,
                    }
                if r["schema_version"] != model.REVIEW_SCHEMA:
                    continue
                card = model.coding_source(h)
                for name in ("municipality", "dwelling_no", "household_no"):
                    pointer = f"/dwelling/households/{hi}/{name}"
                    if name in h:
                        ref = Reference(
                            region,
                            card["image"],
                            card["page"],
                            pointer,
                            "Reviewer-initiated identity correction",
                        )
                        service.voluntary_references[ref.item_id] = ref
                        service.voluntary_by_card.setdefault(ref.card_id, []).append(
                            ref
                        )
                for bundle in h.get("retained_supplements", []):
                    for c in bundle["payload"].get("cards", []):
                        cid = physical_card_id(region, c["image"], c.get("page"))
                        service.card_registry[cid] = {
                            **c,
                            "region": region,
                            "retained": True,
                            "bundle_id": bundle["id"],
                            "custodian": model.owner(region, h),
                        }
            for c in d.get("cards", []):
                cid = physical_card_id(region, c["image"], c.get("page"))
                service.card_registry[cid] = {**c, "region": region, "retained": False}


def indexes(service, region):
    records, version = service.store.regions[region]
    if any(r["schema_version"] != model.REVIEW_SCHEMA for r in records):
        raise ReviewError(
            "review_preparation_required",
            "Prepare per-card review data before using card operations",
        )
    cached = service.prepared_indexes.get(region)
    if cached is None or cached[0] != version:
        cached = (version, model.inventory(records), model.duplicate_index(records))
        service.prepared_indexes[region] = cached
    return cached[1:]


def card_context(service, card_id):
    with service.store.lock:
        source = service.card_registry.get(card_id)
        if not source or source["role"] != "coding-front":
            raise ReviewError("missing_card", "Unknown physical coding card", 404)
        region = source["region"]
        inv, _ = indexes(service, region)
        _, hi, record, h = inv[card_id]
        fields = []
        for label, pointer, group in field_pointers(hi, review=True):
            if group == "front":
                continue
            ref = Reference(region, source["image"], source["page"], pointer)
            try:
                field = resolve_field([record], ref).field
            except ReviewError as error:
                if error.code == "stale_pointer":
                    continue
                raise
            fields.append(
                {
                    "id": ref.item_id
                    if ref.item_id in service.references
                    or ref.item_id in service.voluntary_references
                    else None,
                    "label": label,
                    "field_path": pointer,
                    "field": {
                        k: deepcopy(v) for k, v in field.items() if k != "review"
                    },
                }
            )
        bundles = deepcopy(h.get("retained_supplements", []))
        for bundle in bundles:
            bundle["scans"] = [
                scan_summary(region, c) for c in bundle["payload"].get("cards", [])
            ]
        return {
            "card_id": card_id,
            "region": region,
            "pdf": source["image"],
            "page": source["page"],
            "identity": model.identity(h),
            "address": record["dwelling"].get("address", {}).get("value"),
            "fields": fields,
            "scan_url": f"/api/scans/{card_id}",
            "fronts": [
                scan_summary(region, c) for c in record["dwelling"].get("cards", [])
            ],
            "retained_supplements": bundles,
            "link_history": [
                {
                    "id": e["id"],
                    "action": e["action"],
                    "reviewer": e["reviewer"],
                    "timestamp": e["timestamp"],
                    "source_pages": [
                        [service.card_registry[c].get("page") for c in f["members"]]
                        for f in e.get("structure", {}).get("before", [])
                    ],
                    "destination_pages": [
                        [service.card_registry[c].get("page") for c in f["members"]]
                        for f in e.get("structure", {}).get("after", [])
                    ],
                }
                for e in h.get("link_history", [])
            ],
            "version": service.store.regions[region][1],
        }


def scan_summary(region, card):
    cid = physical_card_id(region, card["image"], card.get("page"))
    return {**card, "card_id": cid, "scan_url": f"/api/scans/{cid}"}


def item_details(service, ref, resolved):
    h = resolved.household
    inv, duplicates = indexes(service, ref.region)
    cid = model.owner(ref.region, h)
    key = (ref.region, model.coding_source(h)["image"], model.identity(h))
    peers = []
    for other in duplicates.get(key, []):
        if other == cid:
            continue
        _, _, record, household = inv[other]
        c = model.coding_source(household)
        peers.append(
            {
                "card_id": other,
                "page": c["page"],
                "pdf": c["image"],
                "identity": model.identity(household),
                "address": record["dwelling"].get("address", {}).get("value"),
                "scan_url": f"/api/scans/{other}",
            }
        )
    issues = []
    messages = {
        "duplicate_record_id": "Other physical cards have this identity; compare their scans.",
        "incomplete_identity": "Some identity readings are missing or invalid.",
        "missing_card_reading": "Independent readings are missing from retained artifacts.",
    }
    for flag in h.get("flags", []):
        issues.append(
            {"code": flag, "message": messages.get(flag, flag.replace("_", " "))}
        )
    if h.get("relink", {}).get("state") in {"pending", "provisional"}:
        issues.append({"code": "relink_pending", "message": h["relink"]["reason"]})
    active = model.active_links(h)
    return {
        "prepared_review": True,
        "assigned": ref.item_id in service.references,
        "review_issues": issues,
        "duplicate_peers": peers,
        "relink": deepcopy(h.get("relink")),
        "retained_bundle_count": len(h.get("retained_supplements", [])),
        "undo_link_id": active[-1]["id"] if active else None,
        "link_history_count": len(h.get("link_history", [])),
    }


def check_action(item, action, value):
    if item["diagnostics"]:
        raise ReviewError(
            "unsupported_action", "Resolve scan or source diagnostics before reviewing"
        )
    if action not in item["allowed_actions"]:
        raise ReviewError("unsupported_action", "Action is unsupported for this field")
    if action != "correct" and value is not None:
        raise ReviewError("invalid_value", "Only corrections accept a value")
    return item


def preview(service, item_id, action, value, expected_version):
    with service.store.lock:
        ref = service.reference(item_id)
        service.store.check_version(ref.region, expected_version)
        resolved, _ = service.store.current(ref)
        if resolved.record["schema_version"] != model.REVIEW_SCHEMA:
            raise ReviewError(
                "review_preparation_required",
                "Prepare per-card review data before relinking",
            )
        check_action(service.item(item_id, context=False), action, value)
        records = deepcopy(service.store.regions[ref.region][0])
        candidate = resolve_field(records, ref)
        after = field_after(candidate.field, candidate.descriptor, action, value)
        candidate.field.update(after)
        return analyze_candidate(
            service, ref, records, candidate, action, value, expected_version
        )


def analyze_candidate(
    service, ref, records, candidate, action, value, expected_version
):
    """Evaluate one copied candidate; committing does not copy it a second time."""
    published_inv, published_duplicates = indexes(service, ref.region)
    before_conflict = model.conflicts(None, ref.card_id, published_duplicates)
    after_conflict = model.conflicts(records, ref.card_id)
    confirmation = None
    if after_conflict and after_conflict != before_conflict:
        confirmation = model.canonical_hash(
            {
                "version": expected_version,
                "item_id": ref.item_id,
                "action": action,
                "value": value,
                "conflict": after_conflict,
            }
        )
    # Only a changed dwelling identity re-plans membership: re-saving the same
    # value must not move the card.
    published = published_inv[ref.card_id][3]
    changed = (
        action == "correct"
        and candidate.descriptor.identity_kind in {"municipality", "dwelling"}
        and model.dwelling_key(candidate.household) != model.dwelling_key(published)
    )
    membership = (
        model.plan_membership(records, ref.card_id)
        if changed
        else {"outcome": "unchanged", "target_card_id": None, "candidates": []}
    )
    return {
        "version": expected_version,
        "duplicate_confirmation": confirmation,
        "duplicate": after_conflict,
        "membership": membership,
    }


def replay(service, request_id, reviewer, request, item_id):
    prior = service.requests.get(request_id)
    if prior is None:
        return None
    if (
        prior["reviewer"] != reviewer
        or prior["request"] != request
        or prior["item_id"] != item_id
    ):
        raise ReviewError(
            "request_conflict", "Request ID was used for different input", 409
        )
    return result(service, prior, replayed=True)


def result(service, event, *, replayed=False, membership=None):
    source = service.card_registry.get(event.get("card_id"), {})
    item_id = (
        card_item_id(service, source["custodian"])
        if source.get("retained")
        else event["item_id"]
    )
    ref = rebind_reference(service, service.reference(item_id))
    if ref is None:
        raise ReviewError(
            "retained_evidence",
            "Restore retained evidence before reviewing its fields",
            409,
        )
    return {
        "saved_locally": True,
        "replayed": replayed,
        "decision": deepcopy(event),
        "item": service.item(ref.item_id),
        "membership": membership,
        "structural_change": bool(event.get("structure")),
    }


def apply_decision(
    service,
    item_id,
    action,
    reviewer,
    expected_version,
    request_id,
    value=None,
    undo_target=None,
    duplicate_confirmation=None,
):
    reviewer = credentials(reviewer, request_id)
    request = {
        "action": action,
        "value": value,
        "expected_version": expected_version,
        "undo_target": undo_target,
        "duplicate_confirmation": duplicate_confirmation,
    }
    with service.store.lock:
        if prior := replay(service, request_id, reviewer, request, item_id):
            return prior
        ref = service.reference(item_id)
        service.store.check_version(ref.region, expected_version)
        item = service.item(item_id, context=False)
        if item["diagnostics"]:
            raise ReviewError(
                "missing_scan", "Review requires the original readable scan", 404
            )
        service.scans.get_scan(ref)
        if ref.front_page is not None:
            service.scans.get_scan(Reference(ref.region, ref.pdf, ref.front_page, "/"))
        records = deepcopy(service.store.regions[ref.region][0])
        resolved = resolve_field(records, ref)
        field, h = resolved.field, resolved.household
        before, before_state = snapshot(field), state(field)
        history = deepcopy(field.get("review", {}).get("history", []))
        event = {
            "id": str(uuid4()),
            "request_id": request_id,
            "item_id": item_id,
            "card_id": ref.card_id,
            "field_path": ref.field_path,
            "reviewer": reviewer,
            "timestamp": datetime.now(UTC).isoformat(),
            "action": action,
            "before": before,
            "before_state": before_state,
            "request": request,
        }
        membership = None
        if action == "undo":
            if value is not None:
                raise ReviewError("invalid_action", "Undo does not accept a value")
            active = active_decisions(history)
            if not active or active[-1]["id"] != undo_target:
                raise ReviewError(
                    "undo_conflict", "Undo the later decision on this field first", 409
                )
            target = active[-1]
            if "structure" in target:
                model.undo_move(records, target["structure"])
                event["structure"] = reversed_effect(records, target["structure"])
            elif "identity_guard" in target:
                guard = target["identity_guard"]
                current = model.frame(resolved.record)
                if (
                    model.dwelling_key(h) != guard["key"]
                    or model.latest_link_id(h) != guard["link_id"]
                    or set(current["members"]) != set(guard["frame"]["members"])
                    or model.canonical_hash(current["topology"])
                    != model.canonical_hash(guard["frame"]["topology"])
                ):
                    raise ReviewError(
                        "undo_conflict",
                        "This card's dwelling or evidence association changed; undo that dependency first",
                        409,
                    )
            if "structure" not in target and "relink_after" in target:
                if h.get("relink") != target["relink_after"]:
                    raise ReviewError(
                        "undo_conflict",
                        "The card's link state changed; undo that dependency first",
                        409,
                    )
                model.restore_relink(h, target.get("relink_before"))
            after, after_state = deepcopy(target["before"]), target["before_state"]
            event["undo_target"] = undo_target
        else:
            check_action(item, action, value)
            after = field_after(field, resolved.descriptor, action, value)
            after_state = "accepted" if action == "accept" else "corrected"
            if after == before and after_state == before_state:
                raise ReviewError("no_op", "This decision is already recorded")
            if action == "correct" and resolved.descriptor.identity_kind:
                field.update(after)
                analysis = analyze_candidate(
                    service, ref, records, resolved, action, value, expected_version
                )
                if (
                    analysis["duplicate_confirmation"]
                    and analysis["duplicate_confirmation"] != duplicate_confirmation
                ):
                    raise ReviewError(
                        "duplicate_confirmation_required",
                        "Compare the duplicate cards and choose Save anyway",
                        409,
                    )
                membership = analysis["membership"]
        event.update(after=deepcopy(after), after_state=after_state)
        history.append(event)
        field.clear()
        field.update(after, review={"state": after_state, "history": history})
        if membership and resolved.descriptor.identity_kind in {
            "municipality",
            "dwelling",
        }:
            prior_link = deepcopy(h.get("relink"))
            outcome = membership["outcome"]
            if outcome in {"clear", "unmatched"}:
                event["structure"] = model.move(
                    records, ref.card_id, membership["target_card_id"], event["id"]
                )
                h["relink"] = {
                    "state": "auto_linked" if outcome == "clear" else "provisional",
                    "reason": "Moved to compatible front-bearing dwelling"
                    if outcome == "clear"
                    else "No matching dwelling found",
                }
            elif outcome != "unchanged":
                h["relink"] = {
                    "state": "provisional" if outcome == "provisional" else "pending",
                    "reason": {
                        "ambiguous": "Several or conflicting destinations need manual linking",
                        "supplementary_pending": "Confirm moving this card while retaining the former dwelling's evidence separately",
                        "persons_pending": "Person ownership must be settled before moving",
                        "notes_pending": "A source note belongs to this card; settle evidence ownership before moving",
                        "incomplete": "Complete this card's identity before linking",
                        "provisional": "This card has no associated survey front",
                    }[outcome],
                }
            elif h.get("relink", {}).get("state") == "pending":
                # The card fits its group again, so the earlier pending link no longer applies.
                if any(
                    c["role"] == "survey-front"
                    for c in resolved.record["dwelling"].get("cards", [])
                ):
                    h.pop("relink")
                else:
                    h["relink"] = deepcopy(model.UNFRONTED)
            if h.get("relink") != prior_link and "structure" not in event:
                event.update(
                    relink_before=prior_link, relink_after=deepcopy(h.get("relink"))
                )
        if (
            action == "correct"
            and resolved.descriptor.identity_kind in {"municipality", "dwelling"}
            and "structure" not in event
        ):
            # The frame holds no derived IDs or flags, so it precedes refresh.
            current = model.inventory(records)[ref.card_id]
            event["identity_guard"] = {
                "key": model.dwelling_key(h),
                "link_id": model.latest_link_id(h),
                "frame": model.frame(current[2]),
            }
        return commit(service, ref.region, expected_version, records, event, membership)


def commit(service, region, expected_version, records, event, membership=None):
    model.refresh_identities(records)
    model.assert_conservation(service.store.regions[region][0], records)
    service.store.save(region, expected_version, records)
    service.reindex_history({region})
    return result(service, event, membership=membership)


def reversed_effect(records, original):
    # Reversal audit records describe topology, never a second live evidence copy.
    ids = {c for f in original["before"] for c in f["members"]}
    current = [
        model.frame(r)
        for r in records
        if any(model.owner(r["region"], h) in ids for h in r["dwelling"]["households"])
    ]
    return {
        **deepcopy(original),
        "before": deepcopy(original["after"]),
        "after": current,
        "bundle_id": None,
    }


def link_candidates(service, card_id):
    with service.store.lock:
        context = card_context(service, card_id)
        records = service.store.regions[context["region"]][0]
        inv, _ = indexes(service, context["region"])
        plan = model.plan_membership(records, card_id, inv)
        return {
            **plan,
            "version": context["version"],
            "requires_retention": len(inv[card_id][2]["dwelling"]["households"]) == 1
            and model.has_supplements(inv[card_id][2]),
        }


def card_item_id(service, card_id):
    refs = [r for r in service.references.values() if r.card_id == card_id]
    refs += [r for r in service.voluntary_references.values() if r.card_id == card_id]
    if not refs:
        raise ReviewError("missing_item", "No review identity fields on this card", 404)
    return refs[0].item_id


def link(
    service,
    card_id,
    target_card_id,
    retain_supplements,
    reviewer,
    expected_version,
    request_id,
):
    reviewer = credentials(reviewer, request_id)
    request = {
        "action": "link",
        "target_card_id": target_card_id,
        "retain_supplements": retain_supplements,
        "expected_version": expected_version,
        "undo_target": None,
    }
    with service.store.lock:
        item_id = card_item_id(service, card_id)
        if prior := replay(service, request_id, reviewer, request, item_id):
            return prior
        candidates = link_candidates(service, card_id)  # validates the card
        source = service.card_registry[card_id]
        region = source["region"]
        service.store.check_version(region, expected_version)
        if target_card_id is not None and target_card_id not in {
            c["card_id"] for c in candidates["candidates"] if not c["current"]
        }:
            raise ReviewError(
                "invalid_destination",
                "Choose a current compatible destination in this region and PDF",
            )
        if candidates["outcome"] == "incomplete":
            raise ReviewError(
                "incomplete_identity",
                "Complete municipality and dwelling number before linking",
            )
        service.scans.get_scan(Reference(region, source["image"], source["page"], "/"))
        if target_card_id:
            target = service.card_registry[target_card_id]
            service.scans.get_scan(
                Reference(region, target["image"], target["page"], "/")
            )
        records = deepcopy(service.store.regions[region][0])
        event = {
            "id": str(uuid4()),
            "item_id": item_id,
            "card_id": card_id,
            "request_id": request_id,
            "reviewer": reviewer,
            "timestamp": datetime.now(UTC).isoformat(),
            "action": "link",
            "request": request,
        }
        event["structure"] = model.move(
            records, card_id, target_card_id, event["id"], retain=retain_supplements
        )
        h = model.inventory(records)[card_id][3]
        h["relink"] = {
            "state": "manual_linked" if target_card_id else "provisional",
            "reason": "Reviewer selected dwelling"
            if target_card_id
            else "Reviewer selected coding-only provisional dwelling",
        }
        h.setdefault("link_history", []).append(event)
        return commit(service, region, expected_version, records, event)


def undo_link(service, target, reviewer, expected_version, request_id):
    reviewer = credentials(reviewer, request_id)
    request = {
        "action": "undo",
        "target_card_id": None,
        "retain_supplements": False,
        "expected_version": expected_version,
        "undo_target": target["id"],
    }
    with service.store.lock:
        if prior := replay(service, request_id, reviewer, request, target["item_id"]):
            return prior
        card_id = target["card_id"]
        context = card_context(service, card_id)
        region = context["region"]
        service.store.check_version(region, expected_version)
        records = deepcopy(service.store.regions[region][0])
        h = model.inventory(records)[card_id][3]
        active = model.active_links(h)
        if not active or active[-1]["id"] != target["id"]:
            raise ReviewError(
                "undo_conflict", "Undo the later link operation first", 409
            )
        service.scans.get_scan(Reference(region, context["pdf"], context["page"], "/"))
        model.undo_move(records, target["structure"])
        event = {
            "id": str(uuid4()),
            "request_id": request_id,
            "item_id": target["item_id"],
            "card_id": card_id,
            "reviewer": reviewer,
            "timestamp": datetime.now(UTC).isoformat(),
            "action": "undo",
            "request": request,
            "undo_target": target["id"],
            "structure": reversed_effect(records, target["structure"]),
        }
        h.setdefault("link_history", []).append(event)
        return commit(service, region, expected_version, records, event)

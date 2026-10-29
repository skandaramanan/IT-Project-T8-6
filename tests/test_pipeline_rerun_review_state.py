"""A rerun's merge keeps review link state and re-resolves a regrouped note."""

import json
from copy import deepcopy

import pytest
from test_review_relinking import (
    correct,
    current,
    grouped,
    raw_record,
    restart,
    start,
    undo,
    with_front,
)

from survey.association.notes import assign_household
from survey.pipeline import MergeRefused, _merge
from survey.review.prepared_service import link
from survey.review.relinking import UNFRONTED, finish_records, owner


def rewrite(service, records):
    path = service.store.directory / "demo.jsonl"
    path.write_text("".join(json.dumps(record) + "\n" for record in records))
    return restart(service)


def test_rerun_keeps_a_pending_relink_so_undo_still_works(tmp_path):
    initial = [
        raw_record(1),
        with_front(raw_record(2, "7"), 3, "7"),
        with_front(raw_record(4, "7"), 5, "7"),
    ]
    service = start(tmp_path, deepcopy(initial))
    saved = correct(service, 1, "dwelling_no", "7")
    pending = current(service, 1)[3]["relink"]
    assert pending["state"] == "pending"

    old = deepcopy(service.store.regions["demo"][0])
    merged = _merge(old, finish_records(deepcopy(initial)))
    (household,) = [
        h
        for record in merged
        for h in record["dwelling"]["households"]
        if h["cards"][0]["page"] == 1
    ]
    assert household["relink"] == pending
    undo(rewrite(service, merged), saved)


def test_rerun_refuses_to_split_a_reviewer_link(tmp_path):
    initial = [
        raw_record(1, "7"),
        with_front(raw_record(3, "7", household="2"), 4, "7"),
    ]
    service = start(tmp_path, deepcopy(initial))
    card = owner("demo", current(service, 1)[3])
    target = owner("demo", current(service, 3)[3])
    version = service.store.regions["demo"][1]
    link(service, card, target, False, "Reviewer", version, "link-1")

    old = deepcopy(service.store.regions["demo"][0])
    with pytest.raises(MergeRefused, match="regrouped"):
        _merge(old, finish_records(deepcopy(initial)))


def test_regrouped_note_drops_its_card_link_and_re_resolves():
    old = with_front(raw_record(3, "7"), 4, "7")
    old["dwelling"]["notes"] = [
        {
            "front_page": 4,
            "page": None,
            "household_id": None,
            "text": {
                "value": "lodger",
                "status": "ok",
                "confidence": None,
                "source": "survey-back",
            },
        }
    ]
    assign_household(old["dwelling"]["notes"][0], old["dwelling"]["households"])
    finish_records([old])
    assert old["dwelling"]["notes"][0]["household_card_id"]

    new = with_front(
        grouped(raw_record(3, "7"), raw_record(5, "7", household="2")), 4, "7"
    )
    (note,) = _merge([old], [new])[0]["dwelling"]["notes"]
    assert note["household_id"] is None
    assert "household_ambiguous" in note["flags"]


def test_rerun_refuses_to_regain_a_retained_front(tmp_path):
    initial = [
        with_front(raw_record(1, "6"), 2, "6"),
        with_front(raw_record(3, "7"), 4, "7"),
    ]
    service = start(tmp_path, deepcopy(initial))
    card = owner("demo", current(service, 1)[3])
    version = service.store.regions["demo"][1]
    link(service, card, None, True, "Reviewer", version, "link-1")

    old = deepcopy(service.store.regions["demo"][0])
    with pytest.raises(MergeRefused, match="regrouped"):
        _merge(old, finish_records(deepcopy(initial)))


def test_rerun_drops_the_unfronted_label_once_a_front_is_found():
    old = finish_records([raw_record(1)])
    household = old[0]["dwelling"]["households"][0]
    assert household["relink"] == UNFRONTED
    household["house"]["garden"].update(
        value="2", origin="corrected", original_value="1"
    )

    (record,) = _merge(old, finish_records([with_front(raw_record(1), 2, "6")]))
    assert "relink" not in record["dwelling"]["households"][0]

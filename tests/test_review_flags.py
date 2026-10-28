"""The review queue (FR-11, D022), as review flags."""

import copy
import json
import random

import pytest
from review_support import legacy

from survey import cli
from survey.extraction.card_fields import FIELD_SCHEMA, FIELD_SCHEMA_BY_NAME
from survey.extraction.record import FIELD_MAP, build_record
from survey.records import current_fields
from survey.review.flags import build_flags
from survey.review.routing import AGREE_CONFIDENCE


def record(record_id="27-0006-01", region="216412", card_confidence=None, **scores):
    """A real record, every field cleared (ok at the calibrated agree cutoff) except ``scores``:
    ``coding__weekly_rent=0.5`` scores ``households[0].coding.weekly_rent``.
    Its coding card is page ``int(dwelling number)`` of ``unit.pdf``."""
    municipality, dwelling, household = record_id.split("-")
    fields = {label: "1" for label in FIELD_SCHEMA_BY_NAME} | {
        "Municipality": municipality,
        "Number of Dwelling": dwelling,
        "Number of Household": household,
    }
    # These cover the published 0.6.0 queue (shared first-card fields).
    built = legacy(
        build_record(fields, region=region, image="unit.pdf", page=int(dwelling))
    )
    for _, field in current_fields(built):
        field |= {"status": "ok", "confidence": AGREE_CONFIDENCE}
    built["dwelling"]["households"][0]["cards"][0]["confidence"] = card_confidence
    for name, score in scores.items():
        group, key = name.split("__")
        node = built["dwelling"]
        node = node if group == "house" else node["households"][0]
        node[group][key]["confidence"] = score
    return built


def label_of(pointer):
    key = pointer.rsplit("/", 1)[1]
    return next(label for label, (k, _) in FIELD_MAP.items() if k == key)


def flags(*records):
    regions = {}
    for r in records:
        regions.setdefault(r["region"], []).append(r)
    queue, skipped = build_flags(regions)
    assert skipped == []
    return queue


def test_only_fields_the_rule_flags_are_queued():
    one = record(house__garden=0.75, coding__weekly_rent=None)
    one["dwelling"]["house"]["bathroom"]["status"] = "illegible"
    assert [(f["field_path"], f["reason"]) for f in flags(one)] == [
        ("/dwelling/households/0/coding/weekly_rent", "no score"),
        ("/dwelling/house/garden", "score 0.75"),
        ("/dwelling/house/bathroom", "illegible"),
    ]
    assert flags(record()) == []


def test_each_card_is_queued_in_printed_order_across_columns():
    """FIELD_SCHEMA is the card's reading order; FIELD_MAP groups by storage."""
    one = record(
        house__bathroom=0.5,
        head__age_of_head=0.5,
        coding__weekly_rent=0.5,
        counts__number_under_5=0.5,
        house__garden=0.5,
    )
    printed = [spec.name for spec in FIELD_SCHEMA]
    labels = [label_of(f["field_path"]) for f in flags(one)]
    assert labels == sorted(labels, key=printed.index)
    assert labels.index("Weekly Rent") < labels.index("Garden")


def test_only_coding_card_fields_are_queued():
    """Front and person fields aren't reviewable yet, however unsure."""
    one = record(house__garden=0.5)
    unsure = {"value": "x", "status": "ok", "confidence": 0.1}
    one["dwelling"]["address"] = unsure | {"source": "survey-front"}
    one["dwelling"]["households"][0]["persons"] = [{"age": unsure}]
    assert [f["field_path"] for f in flags(one)] == ["/dwelling/house/garden"]


def test_a_field_missing_from_the_record_is_not_queued():
    one = record(house__garden=0.5)
    del one["dwelling"]["house"]["bathroom"]
    assert [f["field_path"] for f in flags(one)] == ["/dwelling/house/garden"]


@pytest.mark.parametrize(
    ("reviewed", "flagged"),
    [
        ({"review": {"state": "accepted"}}, False),
        ({"review": {"state": "corrected"}}, False),
        ({"origin": "corrected"}, False),
        ({"review": {"state": "pending"}}, True),  # undone
    ],
)
def test_a_reviewed_field_leaves_the_queue_until_undone(reviewed, flagged):
    one = record(house__garden=0.5)
    one["dwelling"]["house"]["garden"] |= reviewed
    assert len(flags(one)) == flagged


def test_the_same_batch_gives_the_same_queue_in_any_order():
    batch = [
        record("27-0006-01", card_confidence=0.6, coding__weekly_rent=0.5),
        record("27-0007-01", region="216420", card_confidence=0.6, house__garden=0.5),
        record("31-0001-01", house__garden=0.9),
    ]
    expected = flags(*batch)
    for seed in range(5):
        random.Random(seed).shuffle(batch)
        assert flags(*batch) == expected


def test_least_sure_card_first_and_each_flag_carries_its_region():
    batch = [
        record("27-0001-01", card_confidence=0.9, house__garden=0.1),
        record("27-0002-01", region="216420", card_confidence=0.5, house__garden=0.8),
        record("27-0003-01", card_confidence=None, house__garden=0.9),
        record("27-0004-01", card_confidence=0.0, house__garden=0.9),
    ]
    assert [(f["page"], f["region"]) for f in flags(*batch)] == [
        (3, "216412"),  # no card score is the worst case
        (4, "216412"),
        (2, "216420"),
        (1, "216412"),
    ]


def test_a_card_stays_together_when_two_regions_share_its_id():
    a = record(card_confidence=0.5, house__garden=0.5, coding__weekly_rent=0.5)
    b = record(region="216420", card_confidence=0.5, house__garden=0.5)
    b["dwelling"]["households"][0]["coding"]["weekly_rent"]["confidence"] = 0.5
    assert [f["region"] for f in flags(a, b)] == ["216412"] * 2 + ["216420"] * 2


def test_each_flag_points_at_its_field_on_its_household_card():
    two = record("27-0012-01", house__garden=0.5)
    second = copy.deepcopy(two["dwelling"]["households"][0])
    second["record_id"] = "27-0012-02"
    second["cards"][0]["page"] = 13
    second["coding"]["weekly_rent"]["confidence"] = 0.5
    two["dwelling"]["households"].append(second)

    assert [(f["pdf"], f["page"], f["field_path"]) for f in flags(two)] == [
        ("unit.pdf", 12, "/dwelling/house/garden"),  # dwelling-level: first card
        ("unit.pdf", 13, "/dwelling/households/1/coding/weekly_rent"),
    ]


def test_a_later_household_queues_its_own_municipality():
    two = record("27-0012-01")
    second = copy.deepcopy(two["dwelling"]["households"][0])
    second["record_id"] = "27-0012-02"
    second["cards"][0]["page"] = 13
    second["municipality"]["confidence"] = 0.91
    two["dwelling"]["households"].append(second)
    assert [(f["page"], f["field_path"]) for f in flags(two)] == [
        (13, "/dwelling/households/1/municipality"),
    ]
    two["dwelling"]["municipality"]["confidence"] = 0.5
    assert [(f["page"], f["field_path"]) for f in flags(two)] == [
        (12, "/dwelling/municipality"),
        (13, "/dwelling/households/1/municipality"),
    ]


def test_a_flagged_dwelling_queues_its_identity_fields_whatever_they_score():
    two = record("27-0012-01", house__garden=0.5)
    second = copy.deepcopy(two["dwelling"]["households"][0])
    second["record_id"] = "27-0012-02"
    second["cards"][0]["page"] = 13
    two["dwelling"]["households"].append(second)
    two["dwelling"]["flags"] = ["identity_reread"]
    assert [(f["page"], f["field_path"], f["reason"]) for f in flags(two)] == [
        (12, "/dwelling/municipality", "dwelling flagged identity_reread"),
        (12, "/dwelling/dwelling_no", "dwelling flagged identity_reread"),
        (12, "/dwelling/households/0/household_no", "dwelling flagged identity_reread"),
        (12, "/dwelling/house/garden", "score 0.5"),
        (13, "/dwelling/households/1/municipality", "dwelling flagged identity_reread"),
        (13, "/dwelling/households/1/household_no", "dwelling flagged identity_reread"),
    ]
    # A reviewed identity field leaves the queue like any other.
    two["dwelling"]["dwelling_no"]["review"] = {"state": "accepted"}
    assert "/dwelling/dwelling_no" not in {f["field_path"] for f in flags(two)}


def write(tmp_path, *records, name="216412.jsonl"):
    path = tmp_path / name
    path.write_text("".join(json.dumps(r) + "\n" for r in records))
    return path


def test_the_command_prints_flags_as_json_lines_from_files_or_a_folder(
    tmp_path, capsys
):
    batch = [record(house__garden=0.5), record("27-0007-01", coding__weekly_rent=0.5)]
    write(tmp_path, *batch)

    for target in (tmp_path / "216412.jsonl", tmp_path):
        assert cli.main(["flags", str(target)]) == 0
        lines = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
        assert lines == flags(*batch)


def test_a_broken_line_names_its_file_and_line_and_prints_nothing(tmp_path, capsys):
    path = write(tmp_path, record(house__garden=0.5))
    path.write_text(path.read_text() + "\n{not json\n")

    with pytest.raises(SystemExit):
        cli.main(["flags", str(path)])
    out, err = capsys.readouterr()
    assert "216412.jsonl" in err
    assert out == ""


def test_a_household_with_no_coding_card_is_skipped_and_reported(tmp_path, capsys):
    two = record("27-0012-01", house__garden=0.5)
    second = copy.deepcopy(two["dwelling"]["households"][0])
    second |= {"record_id": "27-0012-02", "cards": []}
    two["dwelling"]["households"].append(second)
    other = record("27-0013-01", house__garden=0.5)

    assert cli.main(["flags", str(write(tmp_path, two, other))]) == 1
    out, err = capsys.readouterr()
    assert [json.loads(line)["page"] for line in out.splitlines()] == [12, 13]
    assert "27-0012-02" in err


def test_a_missing_file_stops_the_command(tmp_path, capsys):
    with pytest.raises(SystemExit):
        cli.main(["flags", str(tmp_path / "216412.jsonl")])
    assert "no such file" in capsys.readouterr().err


def test_a_card_with_no_score_or_no_page():
    unscored = record("27-0001-01", house__garden=0.5)
    del unscored["dwelling"]["households"][0]["cards"][0]["confidence"]
    pageless = record("27-0002-01", card_confidence=0.0, house__garden=0.5)
    pageless["dwelling"]["households"][0]["cards"][0]["page"] = None

    queue, skipped = build_flags({"216412": [unscored, pageless]})
    assert [f["page"] for f in queue] == [1]  # no score: least sure
    assert skipped == ["216412: a card in unit.pdf has no page"]


def test_a_card_on_two_households_is_skipped():
    a, b = record("27-0001-01", house__garden=0.5), record("27-0002-01")
    b["dwelling"]["households"][0]["cards"][0]["page"] = 1
    b["dwelling"]["households"][0]["coding"]["weekly_rent"]["confidence"] = 0.5
    queue, skipped = build_flags({"216412": [a, b]})
    assert queue == []
    assert skipped == ["216412: unit.pdf p1 is on two households"]


@pytest.mark.parametrize("folder", [False, True])
def test_cli_skips_duplicate_cards_and_keeps_valid_flags(tmp_path, capsys, folder):
    a = record("27-0001-01", house__garden=0.5)
    b = record("27-0002-01", house__garden=0.5)
    b["dwelling"]["households"][0]["cards"][0]["page"] = 1
    valid = record("27-0003-01", house__garden=0.5)
    path = write(tmp_path, a, b, valid)

    assert cli.main(["flags", str(tmp_path if folder else path)]) == 1

    out, err = capsys.readouterr()
    assert [json.loads(line) for line in out.splitlines()] == flags(valid)
    assert "216412: unit.pdf p1 is on two households, skipped" in err


def test_dwelling_front_and_back_cards_do_not_enter_coding_generator():
    one = record(house__garden=0.5)
    one["dwelling"]["cards"] = [
        {"role": "survey-front", "image": "unit.pdf", "page": 1},
        {"role": "survey-back", "image": "unit.pdf", "page": 2},
    ]
    assert [f["field_path"] for f in flags(one)] == ["/dwelling/house/garden"]

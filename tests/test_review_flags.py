"""The review queue (FR-11, D022), as review flags."""

import copy
import json
import random

import pytest

from survey import cli
from survey.extraction.card_fields import FIELD_SCHEMA_BY_NAME
from survey.extraction.record import build_record
from survey.review.flags import build_flags, walk_fields


def record(record_id="27-0006-01", region="216412", card_confidence=None, **scores):
    """A real record, every field cleared (ok at 0.97) except ``scores``:
    ``coding__weekly_rent=0.5`` scores ``households[0].coding.weekly_rent``.
    Its coding card is page ``int(dwelling number)`` of ``unit.pdf``."""
    municipality, dwelling, household = record_id.split("-")
    fields = {label: "1" for label in FIELD_SCHEMA_BY_NAME} | {
        "Municipality": municipality,
        "Number of Dwelling": dwelling,
        "Number of Household": household,
    }
    built = build_record(fields, region=region, image="unit.pdf", page=int(dwelling))
    for _, field in walk_fields(built):
        field |= {"status": "ok", "confidence": 0.97}
    built["dwelling"]["households"][0]["cards"][0]["confidence"] = card_confidence
    for name, score in scores.items():
        group, key = name.split("__")
        node = built["dwelling"]
        node = node if group == "house" else node["households"][0]
        node[group][key]["confidence"] = score
    return built


def test_only_fields_the_rule_flags_are_queued():
    batch = [record(house__garden=0.75, coding__weekly_rent=None)]
    batch[0]["dwelling"]["house"]["bathroom"]["status"] = "illegible"
    assert sorted((f["field_path"], f["reason"]) for f in build_flags(batch)) == [
        ("/dwelling/house/bathroom", "illegible"),
        ("/dwelling/house/garden", "score 0.75"),
        ("/dwelling/households/0/coding/weekly_rent", "no score"),
    ]
    assert build_flags([record()]) == []


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
    batch = [record(house__garden=0.5)]
    batch[0]["dwelling"]["house"]["garden"] |= reviewed
    assert len(build_flags(batch)) == flagged


def test_the_same_batch_gives_the_same_queue_in_any_order():
    batch = [
        record("27-0006-01", card_confidence=0.6, coding__weekly_rent=0.5),
        record("27-0007-01", region="216420", card_confidence=0.6, house__garden=0.5),
        record("31-0001-01", house__garden=0.9),
    ]
    expected = build_flags(batch)
    for seed in range(5):
        random.Random(seed).shuffle(batch)
        assert build_flags(batch) == expected


def test_least_sure_card_first_and_each_flag_carries_its_region():
    batch = [
        record("27-0001-01", card_confidence=0.9, house__garden=0.1),
        record("27-0002-01", region="216420", card_confidence=0.5, house__garden=0.8),
        record("27-0003-01", card_confidence=None, house__garden=0.9),
        record("27-0004-01", card_confidence=0.0, house__garden=0.9),
    ]
    assert [(f["page"], f["region"]) for f in build_flags(batch)] == [
        (3, "216412"),  # no card score is the worst case
        (4, "216412"),
        (2, "216420"),
        (1, "216412"),
    ]


def test_each_flag_points_at_its_field_on_its_household_card():
    two = record("27-0012-01", house__garden=0.5)
    second = copy.deepcopy(two["dwelling"]["households"][0])
    second["record_id"] = "27-0012-02"
    second["cards"][0]["page"] = 13
    second["coding"]["weekly_rent"]["confidence"] = 0.5
    two["dwelling"]["households"].append(second)

    assert [(f["pdf"], f["page"], f["field_path"]) for f in build_flags([two])] == [
        ("unit.pdf", 12, "/dwelling/house/garden"),  # dwelling-level: first card
        ("unit.pdf", 13, "/dwelling/households/1/coding/weekly_rent"),
    ]


def test_the_command_prints_flags_as_json_lines(tmp_path, capsys):
    batch = [record(house__garden=0.5), record("27-0007-01", coding__weekly_rent=0.5)]
    results = tmp_path / "216412.jsonl"
    results.write_text("".join(json.dumps(r) + "\n" for r in batch))

    assert cli.main(["flags", str(results)]) == 0
    lines = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert lines == build_flags(batch)


def test_a_broken_line_names_its_file_and_line_and_prints_nothing(tmp_path, capsys):
    results = tmp_path / "216412.jsonl"
    results.write_text(json.dumps(record(house__garden=0.5)) + "\n\n{not json\n")

    with pytest.raises(SystemExit):
        cli.main(["flags", str(results)])
    out, err = capsys.readouterr()
    assert "216412.jsonl line 3" in err
    assert out == ""


def test_a_household_with_no_coding_card_stops_the_command(tmp_path, capsys):
    two = record("27-0012-01", house__garden=0.5)
    second = copy.deepcopy(two["dwelling"]["households"][0])
    second |= {"record_id": "27-0012-02", "cards": []}
    second["coding"]["weekly_rent"]["confidence"] = 0.5
    two["dwelling"]["households"].append(second)
    results = tmp_path / "216412.jsonl"
    results.write_text(json.dumps(two) + "\n")

    with pytest.raises(SystemExit):
        cli.main(["flags", str(results)])
    out, err = capsys.readouterr()
    assert "27-0012-02" in err
    assert out == ""


def test_a_missing_file_stops_the_command(tmp_path, capsys):
    with pytest.raises(SystemExit):
        cli.main(["flags", str(tmp_path / "216412.jsonl")])
    assert "no such file" in capsys.readouterr().err

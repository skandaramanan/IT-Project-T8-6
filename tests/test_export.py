"""FR-15: records survive the JSONL file -- written, read back, rewritten --
without losing values, gaining duplicates or undoing a reviewer's correction."""

import copy
import json
from pathlib import Path

from survey.export import read_jsonl, write_jsonl

EXAMPLE = json.loads(
    (Path(__file__).parent.parent / "schema/example-r01-excerpt.json").read_text()
)


def _household(record: dict, number: int) -> dict:
    """``record`` re-labelled as household ``number`` of the same dwelling."""
    record = copy.deepcopy(record)
    household = record["dwelling"]["households"][0]
    household["record_id"] = f"27-0006-{number:02d}"
    household["household_no"]["value"] = str(number)
    return record


def test_a_record_reads_back_exactly_as_written(tmp_path):
    path = tmp_path / "williamstown.jsonl"

    assert write_jsonl(path, [EXAMPLE]) == []

    # Statuses, null confidence, the 999 sentinel, origin/original_value,
    # source and the nesting all come back unchanged.
    assert read_jsonl(path) == [EXAMPLE]


def test_a_rerun_changes_nothing(tmp_path):
    path = tmp_path / "williamstown.jsonl"
    write_jsonl(path, [EXAMPLE])
    first = path.read_text()

    write_jsonl(path, [EXAMPLE])

    assert path.read_text() == first


def test_households_of_one_dwelling_share_its_line(tmp_path):
    path = tmp_path / "williamstown.jsonl"

    write_jsonl(path, [_household(EXAMPLE, 2)])
    write_jsonl(path, [_household(EXAMPLE, 1)])

    (record,) = read_jsonl(path)
    ids = [h["record_id"] for h in record["dwelling"]["households"]]
    assert ids == ["27-0006-01", "27-0006-02"]


def test_a_rerun_keeps_a_reviewer_correction(tmp_path):
    path = tmp_path / "williamstown.jsonl"
    write_jsonl(path, [EXAMPLE])
    rerun = copy.deepcopy(EXAMPLE)
    house = rerun["dwelling"]["house"]
    house["number_of_sleepouts"] = {**house["number_of_sleepouts"], "value": "0"}
    del house["number_of_sleepouts"]["origin"]
    del house["number_of_sleepouts"]["original_value"]
    house["garden"]["value"] = "2"
    house["sleepouts"] = house.pop("number_of_sleepouts")  # field renamed

    write_jsonl(path, [rerun])

    (record,) = read_jsonl(path)
    sleepouts = record["dwelling"]["house"]["number_of_sleepouts"]
    assert (sleepouts["value"], sleepouts["origin"]) == ("4", "corrected")
    assert record["dwelling"]["house"]["garden"]["value"] == "2"
    assert record["dwelling"]["house"]["sleepouts"]["value"] == "0"


def test_an_invalid_record_is_reported_and_not_written(tmp_path):
    path = tmp_path / "williamstown.jsonl"
    bad = copy.deepcopy(EXAMPLE)
    bad["dwelling"]["house"]["structural_material"] = "1"  # bare value

    (failure,) = write_jsonl(path, [bad])

    assert failure.startswith("27-0006-01: dwelling/house/structural_material:")
    assert read_jsonl(path) == []

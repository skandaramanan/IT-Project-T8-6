"""Struck-option resolution (D021): struck negates, unstruck is untouched."""

import json
from pathlib import Path

import pytest

from extraction.field_schema import FIELD_SCHEMA_BY_NAME
from extraction.record import FIELD_MAP, build_field, build_record

MANIFEST = json.loads(
    (Path(__file__).parent / "fixtures" / "crossed_out" / "manifest.json").read_text()
)

IDENTITY = {"Municipality": "27", "Number of Dwelling": "6", "Number of Household": "1"}

# What D021 resolves any struck field to, whatever was written underneath.
NEGATED = {
    "value": None,
    "code": None,
    "label": None,
    "status": "no_data",
    "confidence": None,
    "negated": True,
}


def _field(record: dict, label: str) -> dict:
    key, group = FIELD_MAP[label]
    household = record["dwelling"]["households"][0]
    if group == "dwelling":
        return record["dwelling"][key]
    if group == "household":
        return household[key]
    if group == "house":
        return record["dwelling"]["house"][key]
    return household[group][key]


def _marks_by_image(fixture: dict) -> dict[str, list[dict]]:
    """Marks grouped by the image each is on.

    A fixture whose marks span two scans carries the same field twice; keying
    one dict by field name would silently drop all but the last.
    """
    by_image: dict[str, list[dict]] = {}
    for mark in fixture.get("marks", []):
        by_image.setdefault(mark.get("image", fixture.get("image")), []).append(mark)
    return by_image


@pytest.mark.parametrize("fixture", MANIFEST["fixtures"], ids=lambda f: f["id"])
def test_marks_resolve_to_the_value_the_manifest_records(fixture):
    """Asserted against each mark's own recorded expectation, not a constant.

    The manifest carries expect_negated and expected_value per mark. Reading
    them means a future mark that is not expected to negate is checked against
    what it actually claims rather than against D021's current blanket rule.
    """
    for image, marks in _marks_by_image(fixture).items():
        card = {m["field"]: m["original_value"] or "x" for m in marks} | IDENTITY
        struck = {m["field"]: True for m in marks}
        record = build_record(card, region="test", struck=struck)
        for mark in marks:
            field = _field(record, mark["field"])
            where = f"{fixture['id']}/{image}/{mark['field']}"
            assert field["negated"] is mark["expect_negated"], where
            assert field["value"] == mark["expected_value"], where


def test_no_strike_control_is_untouched():
    fixture = next(f for f in MANIFEST["fixtures"] if f["id"] == "no_strike_control")
    card = {entry["field"]: "1" for entry in fixture["must_not_negate"]} | IDENTITY
    record = build_record(card, region="test", struck={})
    for entry in fixture["must_not_negate"]:
        field = _field(record, entry["field"])
        assert field["negated"] is False
        assert field["status"] == "ok"
        assert field["value"] == "1"


def test_corrections_left_alone_when_not_struck():
    """r02's corrected fields: no strike is reported for the surviving
    (corrected) value, so resolution leaves it exactly as read."""
    fixture = next(f for f in MANIFEST["fixtures"] if f["id"] == "real_marks_r02")
    corrections = {e["field"]: "1" for e in fixture["must_not_negate"]}
    record = build_record(corrections | IDENTITY, region="test", struck={})
    for label in corrections:
        field = _field(record, label)
        assert field["negated"] is False
        assert field["value"] == "1"


def test_a_struck_identity_field_does_not_crash_record_id():
    """Municipality carries a card-level stamp near it in the real corpus --
    a false-positive struck flag there must not null out record_id's inputs."""
    card = IDENTITY | {"Sex of Head": "0"}
    struck = {
        "Municipality": True,
        "Number of Dwelling": True,
        "Number of Household": True,
    }
    record = build_record(card, region="test", struck=struck)
    assert record["dwelling"]["municipality"]["value"] == "27"
    assert record["dwelling"]["municipality"]["negated"] is False
    assert record["dwelling"]["households"][0]["record_id"] == "27-0006-01"


def test_no_detector_omits_negated_rather_than_claiming_false():
    """struck=None is an engine that cannot detect strikes at all.

    Emitting negated: false there would claim every field was read and found
    unstruck -- the same false claim build_omitted_field refuses to make.
    """
    card = IDENTITY | {"Sex of Head": "0"}
    without = _field(build_record(card, region="test", struck=None), "Sex of Head")
    looked = _field(build_record(card, region="test", struck={}), "Sex of Head")

    assert "negated" not in without
    assert looked["negated"] is False
    assert without["value"] == looked["value"] == "0"


def test_build_field_not_struck_is_unaffected():
    spec = FIELD_SCHEMA_BY_NAME["Sex of Head"]
    field = build_field(spec, "0", struck=False)
    assert field["negated"] is False
    assert field["value"] == "0"
    assert field["status"] == "ok"


def test_build_field_struck_ignores_the_raw_value():
    """Even a legible raw value is discarded once struck is true (D021)."""
    spec = FIELD_SCHEMA_BY_NAME["Sex of Head"]
    assert build_field(spec, "0", struck=True) == NEGATED

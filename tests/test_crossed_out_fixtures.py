"""The FR-06 crossed-out fixture set is complete and well-formed."""

import json
from pathlib import Path

import pytest
from support import assert_intact_jpeg

from survey.extraction.card_fields import FIELD_SCHEMA_BY_NAME

FIXTURES = Path(__file__).parent / "fixtures"
CROSSED_OUT = FIXTURES / "crossed_out"
MANIFEST = json.loads((CROSSED_OUT / "manifest.json").read_text())

# The marks that occur on coding cards: one ordinary strike through a field,
# and the unmarked control that catches a detector flagging everything. Heavy,
# faint, boundary-overlapping and column-slash marks were dropped: none turned
# up in ~270 cards checked by eye across 24 units or 103 more across 44, and
# the card has no column of option boxes for a slash to cross. Slashes through
# blank cells on the survey front are FR-09's, not FR-06's.
REQUIRED_CASES = {
    "clean_strike",
    "no_strike_control",
}


def _referenced_images(node):
    """Every image name anywhere in the manifest.

    Walks rather than naming each section, so a section added later is covered
    without a matching edit here.
    """
    if isinstance(node, dict):
        if isinstance(node.get("image"), str):
            yield node["image"]
        yield from node.get("images", [])
        for value in node.values():
            yield from _referenced_images(value)
    elif isinstance(node, list):
        for item in node:
            yield from _referenced_images(item)


def test_manifest_declares_its_schema_version():
    assert MANIFEST["schema_version"]


def _claimed_cases() -> set[str]:
    return {
        fixture["required_case"]
        for fixture in MANIFEST["fixtures"]
        if fixture.get("required_case")
    }


@pytest.mark.parametrize("case", sorted(REQUIRED_CASES))
def test_required_case_is_covered(case):
    assert case in _claimed_cases()


def test_no_unexpected_cases_are_claimed():
    # Subset, not equality: a fixture set may carry extra cases beyond the
    # required ones without failing.
    assert _claimed_cases() <= REQUIRED_CASES


def test_every_referenced_image_exists_and_is_an_intact_jpeg():
    names = set(_referenced_images(MANIFEST))

    assert names, "expected at least one referenced image"
    for name in sorted(names):
        # Names are stored relative to tests/fixtures/, so this resolves one
        # way only -- probing for the file would let a typo'd crossed_out name
        # silently match the FR-01 fixture a level up and pass.
        path = FIXTURES / name
        assert path.exists(), f"{name} referenced in manifest but not on disk"
        assert_intact_jpeg(path)


@pytest.mark.parametrize("fixture", MANIFEST["fixtures"], ids=lambda f: f["id"])
def test_every_fixture_asserts_something(fixture):
    has_positive = bool(fixture.get("marks"))
    has_negative = bool(fixture.get("must_not_negate"))
    assert has_positive or has_negative, (
        f"{fixture['id']} asserts nothing -- add 'marks' or 'must_not_negate'"
    )


@pytest.mark.parametrize("fixture", MANIFEST["fixtures"], ids=lambda f: f["id"])
def test_every_named_field_is_a_real_schema_field(fixture):
    """A field name the schema doesn't have asserts nothing about anything.

    Caught by hand once already (Pre-war vs Pre-War); this is the check that
    would have caught it.
    """
    named = [m["field"] for m in fixture.get("marks", [])]
    named += [e["field"] for e in fixture.get("must_not_negate", []) if "field" in e]
    for name in named:
        assert name in FIELD_SCHEMA_BY_NAME, (
            f"{fixture['id']} names {name!r}, which is not a schema field"
        )


@pytest.mark.parametrize("fixture", MANIFEST["fixtures"], ids=lambda f: f["id"])
def test_must_not_negate_entries_have_one_of_two_known_shapes(fixture):
    """Either a per-field claim or a card-level annotation, never a mix.

    Consumers branch on the presence of ``field``; nothing else enforced that
    the two shapes stay distinguishable.
    """
    for entry in fixture.get("must_not_negate", []):
        if "field" in entry:
            assert "images" not in entry, (
                f"{fixture['id']}: a per-field entry must not also carry 'images'"
            )
        else:
            assert entry.get("images") or entry.get("image"), (
                f"{fixture['id']}: a card-level entry needs 'image' or 'images'"
            )


def test_no_strike_controls_carry_no_positive_negation_claim():
    # Selected by the role the manifest declares, not by id: renaming the
    # fixture, or adding a second control, must not drop it from this check.
    controls = [
        f for f in MANIFEST["fixtures"] if f.get("required_case") == "no_strike_control"
    ]
    assert controls
    for fixture in controls:
        assert not fixture.get("marks")
        assert fixture["must_not_negate"]


def test_positive_marks_record_a_negatived_value():
    for fixture in MANIFEST["fixtures"]:
        for mark in fixture.get("marks", []):
            assert mark["expect_negated"] is True
            assert "expected_value" in mark

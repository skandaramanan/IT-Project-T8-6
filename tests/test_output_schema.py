"""The output envelope holds.

Guards docs/decisions/D007 against drift. The schema deliberately leaves field
*names* open — the field set is gated on IT-38 — so what's checkable today is
the envelope: three levels, a composite record_id, and every leaf a field
object rather than a bare value.

The example is an illustrative excerpt of fixture r01, not a complete
transcription of it. Full field coverage belongs to IT-70 and IT-79.
"""

import json
from pathlib import Path
from typing import get_args

import jsonschema
import pytest

from survey.extraction.card_fields import FieldStatus

REPO_ROOT = Path(__file__).parent.parent
SCHEMA_DIR = REPO_ROOT / "schema"
SCHEMA = json.loads((SCHEMA_DIR / "record-envelope.schema.json").read_text())
EXAMPLE = json.loads((SCHEMA_DIR / "example-r01-excerpt.json").read_text())


def test_example_record_validates():
    jsonschema.validate(EXAMPLE, SCHEMA)


def test_bare_values_are_rejected():
    """FR-10: a field without a confidence score must not validate."""
    record = json.loads(json.dumps(EXAMPLE))
    record["dwelling"]["house"]["structural_material"] = "1"

    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(record, SCHEMA)


def test_correction_must_keep_the_machine_value():
    """NFR-05: a corrected field is indistinguishable from an extracted one
    unless it carries what it replaced."""
    record = json.loads(json.dumps(EXAMPLE))
    del record["dwelling"]["house"]["number_of_sleepouts"]["original_value"]

    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(record, SCHEMA)


def test_sentinels_are_values_not_missing_data():
    """FR-08: 999 means 'over £10' and has to stay distinct from no data."""
    income = EXAMPLE["dwelling"]["households"][0]["coding"]["normal_household_income"]

    assert income["status"] == "ok"
    assert income["label"], "a sentinel with no label is indistinguishable from a count"


def test_python_status_vocabulary_matches_schema_enum():
    statuses = SCHEMA["$defs"]["field"]["properties"]["status"]["enum"]

    assert set(get_args(FieldStatus)) == set(statuses)


@pytest.mark.parametrize("status", get_args(FieldStatus))
def test_schema_accepts_each_valid_field_status(status):
    record = json.loads(json.dumps(EXAMPLE))
    record["dwelling"]["house"]["structural_material"]["status"] = status

    jsonschema.validate(record, SCHEMA)


def test_unknown_status_is_rejected():
    record = json.loads(json.dumps(EXAMPLE))
    record["dwelling"]["house"]["structural_material"]["status"] = "unreadable"

    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(record, SCHEMA)


def test_field_without_status_is_rejected():
    record = json.loads(json.dumps(EXAMPLE))
    del record["dwelling"]["house"]["structural_material"]["status"]

    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(record, SCHEMA)


def sources(node):
    """Every `source` card role in a subtree, skipping nested households.

    Households are skipped so a dwelling-level walk stays at the dwelling
    level -- the two scopes resolve against different card sets (D006).
    """
    if isinstance(node, dict):
        if isinstance(node.get("source"), str):
            yield node["source"]
        for key, value in node.items():
            if key != "households":
                yield from sources(value)
    elif isinstance(node, list):
        for item in node:
            yield from sources(item)


def roles(*card_lists):
    return {card["role"] for cards in card_lists for card in cards}


def test_every_card_image_exists():
    """NFR-06: a pointer to a missing scan is worse than no pointer, because
    it still looks trustworthy."""
    dwelling = EXAMPLE["dwelling"]
    cards = dwelling["cards"] + [
        card
        for household in dwelling["households"]
        for card in household.get("cards", [])
    ]

    assert cards, "a record with no cards cannot be traced back to anything"
    for card in cards:
        assert (REPO_ROOT / card["image"]).is_file(), f"{card['image']} does not exist"


def test_every_source_resolves_to_a_card():
    """NFR-06 / D006: cards hang off the household, so a dwelling-level source
    resolves by looking down into its households, and a household's resolves
    against its own cards plus the dwelling's -- never a sibling's."""
    dwelling = EXAMPLE["dwelling"]
    households = dwelling["households"]
    dwelling_cards = dwelling["cards"]

    below = roles(dwelling_cards, *(h.get("cards", []) for h in households))
    for source in sources(dwelling):
        assert source in below, f"dwelling source {source!r} matches no card"

    for household in households:
        available = roles(dwelling_cards, household.get("cards", []))
        for source in sources(household):
            assert source in available, (
                f"household {household['record_id']} source {source!r} matches no card of its own"
            )


def test_an_unknown_card_role_is_rejected():
    """NFR-06: the card_role enum is the list D006 decided on. A sixth card
    type is a decision, not a typo someone lands by accident."""
    record = json.loads(json.dumps(EXAMPLE))
    record["dwelling"]["address"]["source"] = "post-it-note"

    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(record, SCHEMA)


def _with_note(**changes):
    record = json.loads(json.dumps(EXAMPLE))
    record["dwelling"]["notes"][0].update(changes)
    return record


def test_a_note_is_a_field_object_not_bare_text():
    """FR-05 / FR-09: a bare string cannot say whether a back was blank or
    never read -- the field object's status can."""
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(_with_note(text="Very big house"), SCHEMA)


def test_a_note_names_a_household_only_by_record_id():
    jsonschema.validate(_with_note(household_id=None), SCHEMA)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(_with_note(household_id="6"), SCHEMA)


def test_a_note_must_say_which_page_it_came_from():
    """NFR-06: two overflow fronts' backs share a role, so the page is what
    tells their notes apart."""
    record = json.loads(json.dumps(EXAMPLE))
    del record["dwelling"]["notes"][0]["page"]

    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(record, SCHEMA)


def test_notes_are_no_longer_kept_per_household():
    """Superseded by dwelling.notes in 0.3.0: the back belongs to the front,
    and the front to the dwelling."""
    record = json.loads(json.dumps(EXAMPLE))
    record["dwelling"]["households"][0]["notes"] = {"text": None}

    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(record, SCHEMA)


def test_example_is_the_current_schema_version():
    from survey.extraction.record import SCHEMA_VERSION

    assert EXAMPLE["schema_version"] == SCHEMA_VERSION

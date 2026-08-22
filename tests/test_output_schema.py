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

import jsonschema
import pytest

SCHEMA_DIR = Path(__file__).parent.parent / "docs" / "schema"
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

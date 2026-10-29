"""Parsing rejects a response that answers a different question.

A model that emits a placeholder object parses cleanly and leaves every schema
field empty, which scores well on a card that is mostly empty cells -- so the
parser has to reject it rather than let it through as a partial answer.
"""

from survey.extraction.card_fields import FIELD_SCHEMA_BY_NAME
from survey.extraction.json_extraction import parse_confidence_bands, parse_json_fields


def test_placeholder_object_is_rejected():
    assert parse_json_fields('{"A": null, "B": null, "C": null}') is None


def test_partial_answer_is_kept():
    fields = parse_json_fields('{"Municipality": "56", "No. of Dwelling": 83}')
    assert fields == {"Municipality": "56", "No. of Dwelling": "83"}


def test_fenced_and_truncated_output_still_parses():
    fenced = parse_json_fields('```json\n{"Municipality": "56"}\n```')
    assert fenced == {"Municipality": "56"}
    truncated = parse_json_fields('{"Municipality": "56", "No. of Dwelling": "8')
    assert truncated == {"Municipality": "56"}


def test_banded_shape_unwraps_to_the_same_fields():
    """The banded prompt nests each value; everything downstream still expects
    a flat {field: value}, so one parser has to read both shapes."""
    banded = parse_json_fields(
        '{"Municipality": {"value": "56", "confidence": "high"},'
        ' "Weekly Rent": {"value": "04", "confidence": "low"}}'
    )
    assert banded == {"Municipality": "56", "Weekly Rent": "04"}


def test_bands_are_read_back_only_where_reported():
    from survey.extraction.json_extraction import parse_confidence_bands

    bands = parse_confidence_bands(
        '{"Municipality": {"value": "56", "confidence": "HIGH"},'
        ' "Weekly Rent": {"value": "04", "confidence": "not a band"},'
        ' "Garden": "3"}'
    )
    # case-folded; an invented band and a flat value both report nothing rather
    # than a made-up default
    assert bands == {"Municipality": "high"}


def test_unbanded_output_reports_no_bands():
    from survey.extraction.json_extraction import parse_confidence_bands

    assert parse_confidence_bands('{"Municipality": "56"}') == {}
    assert parse_confidence_bands(None) == {}


# --- IT-124: labels written another way -------------------------------------


def test_every_alias_names_a_schema_field():
    from survey.extraction.json_extraction import FIELD_ALIASES

    assert set(FIELD_ALIASES.values()) <= set(FIELD_SCHEMA_BY_NAME)
    assert not set(FIELD_ALIASES) & set(FIELD_SCHEMA_BY_NAME)


def test_a_known_misspelling_is_read_under_the_schemas_label():
    fields = parse_json_fields(
        '{"Washhouse": "1", "Number 5 - 10": "2", "Number of Households": "01"}'
    )
    assert fields["Washouse"] == "1"
    assert fields["Number 5-10"] == "2"
    assert fields["Number of Household"] == "01"


def test_children_nested_under_their_heading_are_read():
    fields = parse_json_fields(
        '{"Children of H. or wife": {"Living": "3", "Dead": "0", "Total": "3"}}'
    )
    assert fields["Children of H. or wife: Living"] == "3"
    assert fields["Children of H. or wife: Total"] == "3"


def test_a_nested_string_is_not_guessed_at():
    fields = parse_json_fields(
        '{"Municipality": "04", "Children of H. or wife": "Total: 0"}'
    )
    assert "Children of H. or wife: Total" not in fields


def test_the_schemas_own_label_wins_even_blank():
    fields = parse_json_fields('{"Washouse": null, "Washhouse": "1"}')
    assert fields["Washouse"] == ""


def test_two_misspellings_that_disagree_are_left_omitted():
    text = (
        '{"Municipality": "04", "Children of H. or wife Living": "1", '
        '"Children of H. or Wife: Living": "2"}'
    )
    assert "Children of H. or wife: Living" not in parse_json_fields(text)


def test_a_misspelt_fields_own_band_and_strike_go_with_it():
    from survey.extraction.json_extraction import parse_struck_fields

    text = (
        '{"Washouse": {"value": "1", "confidence": "high"}, '
        '"Washhouse": {"value": "2", "confidence": "low"}, '
        '"Pre-war Occupation": {"value": "07", "confidence": "low", "struck": true}}'
    )
    bands = parse_confidence_bands(text)
    assert bands["Washouse"] == "high"  # the explicit field's, not the alias's
    assert bands["Pre-War Occupation"] == "low"
    assert parse_struck_fields(text)["Pre-War Occupation"] is True


def test_a_cached_reading_gains_its_misspelt_fields_and_keeps_its_own():
    from survey.extraction.base import ExtractionResult
    from survey.extraction.json_extraction import with_canonical_labels

    cached = ExtractionResult(
        fields={"Municipality": "04", "Washhouse": "1", "Number 5-10": ""},
        raw_text='{"Municipality": "04", "Washhouse": "1", "Number 5-10": null, '
        '"Number 5 - 10": "3"}',
    )
    result = with_canonical_labels(cached)
    assert result.fields["Washouse"] == "1"
    assert result.fields["Number 5-10"] == ""
    assert result.struck is None  # still "nobody looked"
    assert with_canonical_labels(result) == result


def test_labels_with_underscores_for_spaces_are_read_under_the_schemas():
    from survey.extraction.json_extraction import _LABEL_BY_FORM

    assert len(_LABEL_BY_FORM) == len(FIELD_SCHEMA_BY_NAME)  # no two collide
    fields = parse_json_fields(
        '{"Municipality": "04", "Number_of_Dwelling": "487", '
        '"Number of Household": "01", "Number_of_Household": "02", '
        '"Type_of_Dwelling": "2", "Number_5_10": "1", "No._of_Boarders": "0", '
        '"Head\'s_Unearned_I.": "03", "Children_of_H._or_wife:_Living": "3"}'
    )
    assert fields["Number of Dwelling"] == "487"
    assert fields["Type of Dwelling"] == "2"
    assert fields["Number 5-10"] == "1"
    assert fields["No. of Boarders"] == "0"
    assert fields["Head's Unearned I."] == "03"
    assert fields["Children of H. or wife: Living"] == "3"
    assert fields["Number of Household"] == "01"  # explicit beats its twin

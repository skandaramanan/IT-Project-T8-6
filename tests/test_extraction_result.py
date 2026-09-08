"""Confidence is optional, and None means something different from {}.

FR-10 requires a score on every extracted field. D008 makes it optional on the
interface because a local VLM has none to give -- so the two empty cases have
to stay distinguishable: None is "this engine can't", {} is "this engine can,
but this card came back with nothing". Collapse them and the benchmark can no
longer tell an engine that fails FR-10 from one that had a bad card.
"""

from azure_doc_intel_extractor import parse_analyze_result

from extraction.base import ExtractionResult


class _Result:
    """Stands in for the SDK's AnalyzeResult; its fields are mappings."""

    def __init__(self, documents):
        self.documents = documents


class _Doc:
    def __init__(self, fields):
        self.fields = fields


def test_confidence_defaults_to_none_not_empty():
    assert ExtractionResult().confidence is None
    assert ExtractionResult().fields == {}  # fields keeps the {}-not-None rule


def test_azure_parse_keeps_value_and_confidence_together():
    result = parse_analyze_result(
        _Result(
            [
                _Doc(
                    {
                        "Tenure": {"valueString": "3", "confidence": 0.94},
                        "Municipality": {"content": "02", "confidence": 0.5},
                    }
                )
            ]
        )
    )
    assert result.fields == {"Tenure": "3", "Municipality": "02"}
    assert result.confidence == {"Tenure": 0.94, "Municipality": 0.5}


def test_azure_confidence_keys_never_exceed_field_keys():
    """A stray confidence key would silently drop out of any join on fields."""
    result = parse_analyze_result(
        _Result([_Doc({"Tenure": {"valueString": "3"}})])  # no confidence returned
    )
    assert result.fields == {"Tenure": "3"}
    assert result.confidence == {}  # engine can score, just didn't here
    assert result.confidence.keys() <= result.fields.keys()


def test_azure_empty_document_is_empty_not_none():
    result = parse_analyze_result(_Result([]))
    assert result.fields == {}
    assert result.confidence == {}

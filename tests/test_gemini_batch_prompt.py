"""extract_batch must follow self.banded the same way extract does: a banded
run should stay banded whether or not --batch is passed, not silently drop
bands the moment cards get grouped into one request.
"""

import json
from pathlib import Path
from types import SimpleNamespace

from survey.extraction.gemini import GeminiExtractor, banded_batch_prompt, batch_prompt
from survey.extraction.json_extraction import parse_confidence_bands


class _FakeModels:
    def __init__(self, response):
        self._response = response
        self.last_contents = None

    def generate_content(self, model, contents, config):
        self.last_contents = contents
        return self._response


class _FakeClient:
    def __init__(self, response):
        self.models = _FakeModels(response)


def _run_extract_batch(monkeypatch, banded, outer_json):
    response = SimpleNamespace(text=json.dumps(outer_json), usage_metadata=None)
    fake_client = _FakeClient(response)
    monkeypatch.setattr("google.genai.Client", lambda: fake_client)
    monkeypatch.setattr(GeminiExtractor, "_part", lambda self, path: "IMAGE")
    monkeypatch.setenv("GEMINI_CONFIDENCE_BAND", "1" if banded else "")
    extractor = GeminiExtractor()
    results = extractor.extract_batch([Path("a.jpg"), Path("b.jpg")])
    return results, fake_client.models.last_contents[0]


def test_unbanded_batch_still_asks_the_flat_prompt(monkeypatch):
    _, prompt_sent = _run_extract_batch(
        monkeypatch, banded=False, outer_json={"1": {}, "2": {}}
    )
    assert prompt_sent == batch_prompt(2)


def test_banded_batch_asks_the_banded_prompt_and_recovers_the_band(monkeypatch):
    outer = {
        "1": {"Municipality": {"value": "04", "confidence": "high"}},
        "2": {"Municipality": {"value": "07", "confidence": "low"}},
    }
    results, prompt_sent = _run_extract_batch(
        monkeypatch, banded=True, outer_json=outer
    )

    assert prompt_sent == banded_batch_prompt(2)
    assert results[0].fields["Municipality"] == "04"
    assert parse_confidence_bands(results[0].raw_text) == {"Municipality": "high"}
    assert results[1].fields["Municipality"] == "07"
    assert parse_confidence_bands(results[1].raw_text) == {"Municipality": "low"}

"""A batched request that comes back unusable is retried, not banked.

The single-card path already retries a response with no usable JSON in it
(``GeminiExtractor._generate``). The batched path used to keep the first answer
whatever it was, which made the batched arm look worse than the model actually
is for reasons that have nothing to do with batching -- and a response that
parsed to a JSON *list* took the whole batch down with an AttributeError.

No API key and no network: the client is a stub returning canned responses.
"""

import json
from types import SimpleNamespace

import gemini_extractor
from gemini_extractor import GeminiExtractor, _parse_batch_object


def _response(text):
    return SimpleNamespace(
        text=text,
        usage_metadata=SimpleNamespace(
            prompt_token_count=10,
            candidates_token_count=5,
            thoughts_token_count=0,
        ),
    )


class _StubClient:
    """Hands back one canned response per call, in order."""

    def __init__(self, texts):
        self._texts = list(texts)
        self.calls = 0
        self.models = SimpleNamespace(generate_content=self._generate_content)

    def _generate_content(self, **_kwargs):
        self.calls += 1
        return _response(self._texts.pop(0))


def _patch(monkeypatch, texts):
    from google import genai

    client = _StubClient(texts)
    monkeypatch.setattr(genai, "Client", lambda *a, **k: client)
    monkeypatch.setattr(gemini_extractor.time, "sleep", lambda _seconds: None)
    return client


def _cards(tmp_path, count):
    paths = []
    for index in range(count):
        path = tmp_path / f"card{index}.png"
        path.write_bytes(b"not really a png, and nothing here decodes it")
        paths.append(path)
    return paths


def test_a_wrongly_shaped_answer_is_an_empty_batch_not_a_crash():
    # ``outer.get`` on a list raises, and every card in the request is lost to
    # an answer that was merely the wrong shape. The batch has to come back
    # keyed by card number or not at all.
    assert _parse_batch_object('[{"Municipality": "56"}, {"Municipality": "27"}]') == {}
    assert _parse_batch_object('"the cards are unreadable"') == {}
    assert _parse_batch_object("no json at all") == {}
    assert _parse_batch_object('{"1": {"Municipality": "56"}}') == {
        "1": {"Municipality": "56"}
    }


def test_an_unusable_batch_response_is_retried(tmp_path, monkeypatch):
    good = json.dumps({"1": {"Municipality": "56"}, "2": {"Municipality": "27"}})
    client = _patch(monkeypatch, ["Sorry, I cannot read these cards.", good])

    results = GeminiExtractor().extract_batch(_cards(tmp_path, 2))

    assert client.calls == 2
    assert results[0].fields["Municipality"] == "56"
    assert results[1].fields["Municipality"] == "27"


def test_three_unusable_responses_are_scored_not_raised(tmp_path, monkeypatch):
    client = _patch(monkeypatch, ["[]", "[]", "[]"])

    results = GeminiExtractor().extract_batch(_cards(tmp_path, 2))

    assert client.calls == 3
    # Recorded as the failure it is, with the cost still counted -- the run
    # spent those requests whether or not the model said anything usable.
    assert [r.fields for r in results] == [{}, {}]
    assert all(r.cost_usd is None or r.cost_usd >= 0 for r in results)

"""Gemini bills thinking tokens at the output rate, and reports them in a
separate counter from the response tokens.

The whole point of ``cost_usd`` on this candidate is deciding whether Gemini is
affordable over 40k cards. A card that thinks for 4k tokens and answers in 1k
costs five times what the response alone suggests, so dropping
``thoughts_token_count`` would under-report the real bill by most of it.
"""

from types import SimpleNamespace

from survey.extraction.gemini import _cost_usd


def _usage(prompt, candidates, thoughts):
    return SimpleNamespace(
        prompt_token_count=prompt,
        candidates_token_count=candidates,
        thoughts_token_count=thoughts,
    )


def test_thinking_tokens_are_billed_as_output():
    # gemini-3.6-flash: $0.75/$3.75 per Mtok (promotional, through 2026-12-31)
    cost = _cost_usd("gemini-3.6-flash", _usage(4_000, 1_000, 4_000))
    assert cost == (4_000 * 0.75 + 5_000 * 3.75) / 1_000_000


def test_unpriced_model_reports_nothing_rather_than_guessing():
    assert _cost_usd("gemini-9-未来", _usage(1, 1, 1)) is None
    assert _cost_usd("gemini-3.6-flash", None) is None


def test_retry_waits_are_terminal_for_our_own_mistakes():
    """A 404 on a retired model shouldn't cost three attempts and 90s of sleep
    before it reports the one thing you need to read."""
    from survey.extraction.gemini import _retry_wait

    assert _retry_wait(RuntimeError("404 NOT_FOUND ... no longer available"), 1) is None
    assert _retry_wait(RuntimeError("400 INVALID_ARGUMENT"), 1) is None
    # 429 is our quota, clears on the minute; 503 is Google's capacity, seconds
    assert _retry_wait(RuntimeError("429 RESOURCE_EXHAUSTED"), 1) == 30
    assert _retry_wait(RuntimeError("503 UNAVAILABLE"), 1) == 5
    assert _retry_wait(RuntimeError("503 UNAVAILABLE"), 3) == 15  # backs off
    # A stalled request cut off by the client's timeout is retried, not fatal.
    assert _retry_wait(RuntimeError("The read operation timed out"), 1) == 5


def test_the_client_gives_up_on_a_stalled_request(monkeypatch):
    from google import genai

    from survey.extraction.gemini import REQUEST_TIMEOUT_SECONDS, _client

    seen = {}
    monkeypatch.setattr(genai, "Client", lambda **kwargs: seen.update(kwargs))
    _client()
    assert seen["http_options"].timeout == REQUEST_TIMEOUT_SECONDS * 1000

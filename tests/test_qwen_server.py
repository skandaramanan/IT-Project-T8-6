"""The LM Studio/llama.cpp route to Qwen2.5-VL (IT-124): what it sends the
server, and how it picks a model and names its readings."""

import base64
import io
import json

import pytest
from PIL import Image

from survey import cli
from survey.extraction import qwen_server
from survey.extraction.qwen import MAX_PIXELS
from survey.extraction.qwen_server import QwenServerExtractor, fit_to_max_pixels
from survey.pipeline import RunSummary


@pytest.fixture(autouse=True)
def no_server_env(monkeypatch):
    for name in (
        "QWEN_SERVER_URL",
        "QWEN_SERVER_MODEL",
        "QWEN_MAX_PIXELS",
        "QWEN_REPEAT_PENALTY",
        "QWEN_STRUCK_DETECTION",
        "QWEN_SERVER_WEIGHTS",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(qwen_server.time, "sleep", lambda _: None)


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def fake_server(
    monkeypatch,
    models=("qwen2.5-vl-7b-instruct",),
    reply="{}",
    finish_reason="stop",
    errors=(),
    weights="Q6_K",
    model_path=None,
):
    """Answers /models and /chat/completions; returns the chat bodies sent.
    ``errors`` are raised by the first chat requests, one each, in order.
    ``weights`` is LM Studio's quantization for every loaded model (None: not
    LM Studio); ``model_path`` is llama.cpp's /props (None: not llama.cpp)."""
    sent = []
    errors = list(errors)

    def urlopen(request, timeout):
        url = request if isinstance(request, str) else request.full_url
        if url.endswith("/api/v0/models"):
            if weights is None:
                raise qwen_server.urllib.error.URLError("404")
            payload = {
                "data": [
                    {"id": m, "state": "loaded", "quantization": weights}
                    for m in models
                ]
            }
        elif url.endswith("/props"):
            if model_path is None:
                raise qwen_server.urllib.error.URLError("404")
            payload = {"model_path": model_path}
        elif url.endswith("/v1/models"):
            payload = {"data": [{"id": m} for m in models]}
        else:
            sent.append(json.loads(request.data))
            if errors:
                raise errors.pop(0)
            payload = {
                "choices": [
                    {"message": {"content": reply}, "finish_reason": finish_reason}
                ]
            }
        return FakeResponse(json.dumps(payload).encode())

    monkeypatch.setattr(qwen_server.urllib.request, "urlopen", urlopen)
    return sent


def test_fit_keeps_the_budget_and_whole_patches():
    width, height = fit_to_max_pixels(3800, 2400)
    assert width * height <= MAX_PIXELS
    assert width % 28 == 0 and height % 28 == 0
    assert abs(width / height - 3800 / 2400) < 0.05


def test_fit_never_upscales_and_zero_means_native():
    assert fit_to_max_pixels(560, 280) == (560, 280)
    assert fit_to_max_pixels(3800, 2400, 0) == (3780, 2380)


def test_extract_sends_the_prompt_and_a_resized_image(tmp_path, monkeypatch):
    image = tmp_path / "card.png"
    Image.new("RGB", (3800, 2400), "white").save(image)
    sent = fake_server(monkeypatch, reply='```json\n{"Municipality": "04"}\n```')
    extractor = QwenServerExtractor()
    assert extractor.is_available()

    result = extractor.extract(image)

    assert result.fields == {"Municipality": "04"}
    (body,) = sent
    assert body["model"] == "qwen2.5-vl-7b-instruct"
    assert body["temperature"] == 0
    # every sampler named, or the server's presets fill in the rest
    assert (body["top_k"], body["top_p"], body["min_p"]) == (1, 1, 0)
    assert body["repeat_penalty"] == 1.05
    image_part, text_part = body["messages"][0]["content"]
    assert text_part["text"] == qwen_server.EXTRACTION_PROMPT
    png = base64.b64decode(image_part["image_url"]["url"].split(",", 1)[1])
    assert Image.open(io.BytesIO(png)).size == fit_to_max_pixels(3800, 2400)


def test_a_blank_model_is_only_guessed_when_one_is_loaded(monkeypatch):
    fake_server(monkeypatch, models=("a", "b"))
    assert not QwenServerExtractor().is_available()

    monkeypatch.setenv("QWEN_SERVER_MODEL", "b")
    assert QwenServerExtractor().is_available()


def test_no_server_is_unavailable_not_a_crash(monkeypatch):
    def refuse(*args, **kwargs):
        raise ConnectionRefusedError

    monkeypatch.setattr(qwen_server.urllib.request, "urlopen", refuse)
    assert not QwenServerExtractor().is_available()


def test_readings_file_under_their_resolution(monkeypatch):
    # model_id stays put so D016's tables still apply; name is the cache folder.
    assert QwenServerExtractor().name == "qwen2.5-vl-server"
    monkeypatch.setenv("QWEN_MAX_PIXELS", "4000000")
    extractor = QwenServerExtractor()
    assert extractor.name == "qwen2.5-vl-server-4000000px"
    assert extractor.model_id == "qwen2.5-vl"
    monkeypatch.setenv("QWEN_MAX_PIXELS", "0")
    assert QwenServerExtractor().name == "qwen2.5-vl-server-nativepx"
    monkeypatch.delenv("QWEN_MAX_PIXELS")
    monkeypatch.setenv("QWEN_REPEAT_PENALTY", "1")
    assert QwenServerExtractor().name == "qwen2.5-vl-server-rp1"


def test_cli_runs_qwen_into_its_own_file_without_fronts(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("SURVEY_OUTPUT_DIR", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)  # Gemini is not needed
    fake_server(monkeypatch)
    calls = {}

    def fake_run(scan_dir, **kwargs):
        calls.update(kwargs)
        return RunSummary(records=1)

    monkeypatch.setattr(cli, "run", fake_run)
    (tmp_path / "unit.pdf").touch()

    args = [
        "extract",
        str(tmp_path),
        "--region",
        "north",
        "--model",
        "qwen2.5-vl-server",
    ]
    assert cli.main(args) == 0
    assert calls["out_dir"].as_posix() == "results/qwen2.5-vl-server"
    assert calls["extractor"].cache_name == (
        "qwen2.5-vl-server/qwen2.5-vl-7b-instruct-q6_k"
    )
    assert calls["front_extractor"] is None
    assert isinstance(calls["extractor"], QwenServerExtractor)


def test_cli_refuses_qwen_with_no_server(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    fake_server(monkeypatch, models=())
    (tmp_path / "unit.pdf").touch()

    with pytest.raises(SystemExit) as error:
        cli.main(
            ["extract", str(tmp_path), "--model", "qwen2.5-vl-server", "--region", "x"]
        )
    assert error.value.code == 2


def test_struck_detection_is_off_unless_asked_for(tmp_path, monkeypatch):
    image = tmp_path / "card.png"
    Image.new("RGB", (280, 280), "white").save(image)
    reply = '{"Municipality": {"value": "04", "struck": true}, "Tenure": {"value": "1", "struck": false}}'

    sent = fake_server(monkeypatch, reply=reply)
    plain = QwenServerExtractor()
    assert plain.is_available()
    result = plain.extract(image)
    assert result.struck is None  # not looked for, which is not "none found"
    assert sent[0]["messages"][0]["content"][1]["text"] == qwen_server.EXTRACTION_PROMPT

    monkeypatch.setenv("QWEN_STRUCK_DETECTION", "1")
    struck = QwenServerExtractor()
    assert struck.is_available()
    assert struck.name == "qwen2.5-vl-server-struck"
    result = struck.extract(image)
    assert result.struck == {"Municipality": True}
    assert result.fields["Municipality"] == "04"
    assert (
        sent[1]["messages"][0]["content"][1]["text"]
        == qwen_server.STRUCK_EXTRACTION_PROMPT
    )


def _card(tmp_path):
    image = tmp_path / "card.png"
    Image.new("RGB", (280, 280), "white").save(image)
    return image


def _http_error(code, body):
    return qwen_server.urllib.error.HTTPError(
        "http://x/v1/chat/completions", code, "err", {}, io.BytesIO(body.encode())
    )


def test_a_reply_cut_off_at_max_tokens_raises_so_nothing_is_cached(
    tmp_path, monkeypatch
):
    # Repaired, this half-object parses to a partial field set that looks fine.
    fake_server(
        monkeypatch,
        reply='{"Municipality": "04", "Tenure": "1", "Num',
        finish_reason="length",
    )
    extractor = QwenServerExtractor()
    assert extractor.is_available()

    with pytest.raises(RuntimeError, match="cut off"):
        extractor.extract(_card(tmp_path))


def test_a_cut_off_reply_is_a_failed_card_not_a_cached_reading(tmp_path, monkeypatch):
    from survey.pipeline import _reading

    fake_server(monkeypatch, reply='{"Municipality": "0', finish_reason="length")
    extractor = QwenServerExtractor()
    extractor.is_available()
    summary = RunSummary()

    result = _reading(
        _card(tmp_path), tmp_path / "s.pdf", 1, extractor, tmp_path, summary
    )

    assert result is None and summary.failed_cards == 1
    assert not (tmp_path / extractor.name).exists()


def test_readings_cache_under_the_weights_the_server_reports(monkeypatch):
    fake_server(monkeypatch, weights="Q4_K_M")
    extractor = QwenServerExtractor()
    assert extractor.is_available()
    assert extractor.cache_name == "qwen2.5-vl-server/qwen2.5-vl-7b-instruct-q4_k_m"
    assert extractor.config["weights"] == "Q4_K_M"

    # llama.cpp names the GGUF file it was started with instead
    fake_server(monkeypatch, weights=None, model_path=r"C:\models\Qwen-Q6_K.gguf")
    extractor = QwenServerExtractor()
    assert extractor.is_available()
    assert extractor.weights == "Qwen-Q6_K.gguf"


def test_weights_the_server_cannot_name_must_be_set(monkeypatch):
    fake_server(monkeypatch, weights=None)
    extractor = QwenServerExtractor()
    assert not extractor.is_available()
    assert "QWEN_SERVER_WEIGHTS" in extractor.unavailable

    monkeypatch.setenv("QWEN_SERVER_WEIGHTS", "Q6_K")
    extractor = QwenServerExtractor()
    assert extractor.is_available()
    assert extractor.cache_name.endswith("-q6_k")


def test_set_weights_must_agree_with_the_server(monkeypatch):
    # One LM Studio id served both quants in IT-124; the id alone can't tell.
    fake_server(monkeypatch, weights="Q4_K_M")
    monkeypatch.setenv("QWEN_SERVER_WEIGHTS", "Q6_K")
    extractor = QwenServerExtractor()
    assert not extractor.is_available()
    assert "Q4_K_M" in extractor.unavailable


def test_switching_weights_reads_the_card_again(tmp_path, monkeypatch):
    from survey.pipeline import _reading

    card = _card(tmp_path)
    sent = fake_server(monkeypatch, reply='{"Municipality": "04"}', weights="Q6_K")
    q6 = QwenServerExtractor()
    assert q6.is_available()
    assert _reading(card, tmp_path / "s.pdf", 1, q6, tmp_path, RunSummary())
    assert _reading(card, tmp_path / "s.pdf", 1, q6, tmp_path, RunSummary())
    assert len(sent) == 1  # replayed

    sent = fake_server(monkeypatch, reply='{"Municipality": "05"}', weights="Q4_K_M")
    q4 = QwenServerExtractor()
    assert q4.is_available() and q4.name == q6.name
    result = _reading(card, tmp_path / "s.pdf", 1, q4, tmp_path, RunSummary())
    assert len(sent) == 1 and result.fields["Municipality"] == "05"


def test_a_cache_only_rebuild_asks_no_server(tmp_path, monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError("no request expected")

    monkeypatch.setattr(qwen_server.urllib.request, "urlopen", refuse)
    extractor = QwenServerExtractor()
    extractor.cached_only = True
    assert not extractor.is_available()  # which cache?

    monkeypatch.setenv("QWEN_SERVER_MODEL", "qwen/qwen2.5-vl-7b")
    monkeypatch.setenv("QWEN_SERVER_WEIGHTS", "Q6_K")
    extractor = QwenServerExtractor()
    extractor.cached_only = True
    assert extractor.is_available()
    assert extractor.cache_name == "qwen2.5-vl-server/qwen-qwen2.5-vl-7b-q6_k"
    with pytest.raises(RuntimeError, match="cache"):
        extractor.extract(_card(tmp_path))


def test_cached_only_is_the_qwen_servers(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("GEMINI_API_KEY", "test")
    (tmp_path / "unit.pdf").touch()
    with pytest.raises(SystemExit) as error:
        cli.main(["extract", str(tmp_path), "--region", "x", "--cached-only"])
    assert error.value.code == 2


def test_an_http_error_names_the_servers_reason(tmp_path, monkeypatch):
    fake_server(
        monkeypatch,
        errors=[_http_error(400, '{"error":"Context size has been exceeded."}')],
    )
    extractor = QwenServerExtractor()
    extractor.is_available()

    with pytest.raises(RuntimeError, match="Context size has been exceeded"):
        extractor.extract(_card(tmp_path))


def test_a_client_error_is_not_sent_again(tmp_path, monkeypatch):
    sent = fake_server(monkeypatch, errors=[_http_error(400, "bad")])
    extractor = QwenServerExtractor()
    extractor.is_available()

    with pytest.raises(RuntimeError):
        extractor.extract(_card(tmp_path))
    assert len(sent) == 1


@pytest.mark.parametrize(
    "error",
    [
        TimeoutError("timed out"),
        qwen_server.urllib.error.URLError("connection refused"),
        _http_error(503, "loading"),
    ],
    ids=["timeout", "connection", "5xx"],
)
def test_a_transient_failure_is_tried_again(tmp_path, monkeypatch, error):
    sent = fake_server(monkeypatch, reply='{"Municipality": "04"}', errors=[error])
    extractor = QwenServerExtractor()
    extractor.is_available()

    assert extractor.extract(_card(tmp_path)).fields == {"Municipality": "04"}
    assert len(sent) == 2


def test_a_server_that_stays_down_fails_after_the_last_attempt(tmp_path, monkeypatch):
    sent = fake_server(monkeypatch, errors=[TimeoutError("timed out")] * 3)
    extractor = QwenServerExtractor()
    extractor.is_available()

    with pytest.raises(TimeoutError):
        extractor.extract(_card(tmp_path))
    assert len(sent) == qwen_server.ATTEMPTS


@pytest.mark.parametrize(
    "name, value", [("QWEN_MAX_PIXELS", "2MP"), ("QWEN_REPEAT_PENALTY", "high")]
)
def test_a_mistyped_setting_is_named(monkeypatch, name, value):
    monkeypatch.setenv(name, value)
    with pytest.raises(ValueError, match=name):
        QwenServerExtractor()

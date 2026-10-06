"""The extract command: .env loading, and the exit code a scheduled run reads."""

import os

import pytest

from survey import cli
from survey.pipeline import RunSummary


def test_load_env_sets_values_but_never_blanks_or_overrides(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text(
        "# a comment\n"
        "GEMINI_API_KEY='abc'\n"
        "GEMINI_MODEL=\n"
        "SURVEY_OUTPUT_DIR=./elsewhere\n"
    )
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_MODEL", raising=False)
    monkeypatch.setenv("SURVEY_OUTPUT_DIR", "./mine")

    cli.load_env(env)

    assert os.environ["GEMINI_API_KEY"] == "abc"
    assert "GEMINI_MODEL" not in os.environ
    assert os.environ["SURVEY_OUTPUT_DIR"] == "./mine"


@pytest.mark.parametrize(
    ("failed", "code"),
    [({}, 0), ({"failed_cards": 1}, 1), ({"failed_pdfs": 1}, 1)],
)
def test_extract_exits_1_only_when_something_failed(
    tmp_path, monkeypatch, failed, code
):
    monkeypatch.chdir(tmp_path)  # no real .env, and data/runs lands in tmp
    monkeypatch.setenv("GEMINI_API_KEY", "test")
    monkeypatch.delenv("SURVEY_OUTPUT_DIR", raising=False)
    calls = {}

    def fake_run(scan_dir, **kwargs):
        calls.update(kwargs, scan_dir=scan_dir)
        return RunSummary(records=3, **failed)

    monkeypatch.setattr(cli, "run", fake_run)
    (tmp_path / "unit.pdf").touch()

    assert cli.main(["extract", str(tmp_path), "--region", "north"]) == code
    assert calls["region"] == "north"
    assert calls["out_dir"].name == "results"


def test_extract_refuses_without_an_api_key(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    (tmp_path / "unit.pdf").touch()

    with pytest.raises(SystemExit) as error:
        cli.main(["extract", str(tmp_path), "--region", "north"])
    assert error.value.code == 2


def test_extract_refuses_a_folder_with_no_pdfs_before_writing(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("GEMINI_API_KEY", "test")
    monkeypatch.setattr(cli, "run", lambda *a, **k: pytest.fail("run was called"))

    with pytest.raises(SystemExit) as error:
        cli.main(["extract", str(tmp_path), "--region", "north"])
    assert error.value.code == 2

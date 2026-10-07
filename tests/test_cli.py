"""The extract command: .env loading, and the exit code a scheduled run reads."""

import os
from pathlib import Path

import pytest

from survey import cli
from survey.pipeline import MergeRefused, RunSummary


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


def test_extract_reports_a_refused_merge_as_one_line_and_exits_1(
    tmp_path, monkeypatch, caplog
):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("GEMINI_API_KEY", "test")

    def refusing_run(scan_dir, **kwargs):
        raise MergeRefused("x.jsonl line 3: not a valid record")

    monkeypatch.setattr(cli, "run", refusing_run)
    (tmp_path / "unit.pdf").touch()

    assert cli.main(["extract", str(tmp_path), "--region", "north"]) == 1
    assert "x.jsonl line 3: not a valid record; nothing written" in caplog.text


def test_extract_lets_an_unexpected_error_through(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("GEMINI_API_KEY", "test")

    def buggy_run(scan_dir, **kwargs):
        raise ValueError("bug")

    monkeypatch.setattr(cli, "run", buggy_run)
    (tmp_path / "unit.pdf").touch()

    with pytest.raises(ValueError, match="bug"):
        cli.main(["extract", str(tmp_path), "--region", "north"])


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


def test_extract_names_the_region_after_the_scan_folder_by_default(
    tmp_path, monkeypatch
):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("GEMINI_API_KEY", "test")
    monkeypatch.delenv("SURVEY_OUTPUT_DIR", raising=False)
    calls = {}

    def fake_run(scan_dir, **kwargs):
        calls.update(kwargs)
        return RunSummary(records=1)

    monkeypatch.setattr(cli, "run", fake_run)
    unit = tmp_path / "216412"
    unit.mkdir()
    (unit / "scan.pdf").touch()

    assert cli.main(["extract", str(unit)]) == 0
    assert calls["region"] == "216412"
    assert calls["raw_dir"] == Path("data/runs/216412")


@pytest.mark.parametrize("region", ["", "North", "../north", "a/b", "north melbourne"])
def test_extract_refuses_a_region_that_is_not_a_plain_lowercase_name(
    tmp_path, monkeypatch, region
):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("GEMINI_API_KEY", "test")
    monkeypatch.setattr(cli, "run", lambda *a, **k: pytest.fail("run was called"))
    (tmp_path / "unit.pdf").touch()

    with pytest.raises(SystemExit) as error:
        cli.main(["extract", str(tmp_path), "--region", region])
    assert error.value.code == 2


def test_extract_asks_for_a_region_when_the_folder_name_is_not_one(
    tmp_path, monkeypatch, capsys
):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("GEMINI_API_KEY", "test")
    monkeypatch.setattr(cli, "run", lambda *a, **k: pytest.fail("run was called"))
    unit = tmp_path / "Prest Scans"
    unit.mkdir()
    (unit / "scan.pdf").touch()

    with pytest.raises(SystemExit) as error:
        cli.main(["extract", str(unit)])
    assert error.value.code == 2
    assert "--region" in capsys.readouterr().err

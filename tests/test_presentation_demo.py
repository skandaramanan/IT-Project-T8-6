import json
import runpy
import socket
import sys
from pathlib import Path

import pytest
from review_support import setup_review

fcntl = pytest.importorskip("fcntl", reason="Mac/POSIX presentation demo launcher")

DEMO = runpy.run_path(
    str(Path(__file__).parents[1] / "scripts/review_presentation_demo.py")
)


def test_each_run_has_fresh_history_records_and_independent_scans(
    tmp_path, monkeypatch
):
    _, settings = setup_review(tmp_path / "source with spaces")
    source = settings.data_checkout / "results"
    pdf = settings.scan_root / "demo/synthetic.pdf"
    baseline = (source / "demo.jsonl").read_bytes(), pdf.read_bytes()
    (source / "empty.jsonl").write_text("\n")
    (settings.scan_root / "metadata.csv").write_text(
        '\ufeffNode ID,Node Title\ndemo,"Demo catalogue title"\n'
    )
    # The launcher must not inherit the caller's repository or signing setup.
    monkeypatch.setenv("GIT_DIR", "/nonexistent/wrong-repository")
    monkeypatch.setenv("GIT_CONFIG_COUNT", "1")
    monkeypatch.setenv("GIT_CONFIG_KEY_0", "commit.gpgsign")
    monkeypatch.setenv("GIT_CONFIG_VALUE_0", "true")
    sandbox = tmp_path / "sandbox with spaces"
    first = DEMO["prepare"](source, settings.scan_root, sandbox)
    # Add demo-only history and damage copies; the next run must ignore both.
    (first / "data/results/demo.jsonl").write_text("demo changes")
    DEMO["git"](first / "data", "add", "results")
    DEMO["git"](first / "data", "commit", "-m", "Demo-only edits")
    (first / "scans/demo/synthetic.pdf").write_bytes(b"changed scan copy")
    second = DEMO["prepare"](source, settings.scan_root, sandbox)
    assert second != first
    assert DEMO["git"](second / "data", "rev-list", "--count", "HEAD") == "1"
    assert DEMO["git"](first / "data", "rev-list", "--count", "HEAD") == "2"
    assert (second / "data/results/demo.jsonl").read_bytes() == baseline[0]
    assert (second / "scans/demo/synthetic.pdf").read_bytes() == baseline[1]
    assert ((source / "demo.jsonl").read_bytes(), pdf.read_bytes()) == baseline
    assert DEMO["git"](second / "data", "remote", "get-url", "origin") == str(
        second / "remote.git"
    )
    assert (second / "flags.jsonl").read_text() == (first / "flags.jsonl").read_text()
    assert (second / "scans/metadata.csv").read_bytes() == (
        settings.scan_root / "metadata.csv"
    ).read_bytes()
    assert not (second / "data/results/empty.jsonl").exists()
    assert (sandbox / "latest-run.txt").read_text().strip() == str(second)
    assert json.loads((second / "manifest.json").read_text())[
        "excluded_empty_files"
    ] == ["empty.jsonl"]


def test_missing_scans_are_reported_without_fabricated_evidence(tmp_path):
    _, settings = setup_review(tmp_path / "source")
    (settings.scan_root / "demo/synthetic.pdf").unlink()
    run = DEMO["prepare"](
        settings.data_checkout / "results", settings.scan_root, tmp_path / "sandbox"
    )
    assert json.loads((run / "manifest.json").read_text())["missing_scans"] == [
        "demo/synthetic.pdf"
    ]
    assert not (run / "scans/demo/synthetic.pdf").exists()


@pytest.mark.parametrize("destination", ["code", "source", "scans", "ancestor"])
def test_sandbox_cannot_overlap_inputs(tmp_path, destination):
    source, scans = tmp_path / "source", tmp_path / "scans"
    source.mkdir()
    scans.mkdir()
    targets = {
        "code": DEMO["REPO"] / "demo",
        "source": source / "demo",
        "scans": scans / "demo",
        "ancestor": tmp_path,
    }
    with pytest.raises(ValueError, match="separate"):
        DEMO["prepare"](source, scans, targets[destination])
    assert not list(source.iterdir()) and not list(scans.iterdir())


def test_running_demo_lock_prevents_new_run(tmp_path, monkeypatch, capsys):
    source, scans, sandbox = [
        tmp_path / name for name in ("source", "scans", "sandbox")
    ]
    for path in (source, scans, sandbox):
        path.mkdir()
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "demo",
            "--scan-root",
            str(scans),
            "--source-results",
            str(source),
            "--sandbox-root",
            str(sandbox),
            "--prepare-only",
        ],
    )
    with (sandbox / ".launch.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        assert DEMO["main"]() == 1
    assert "already running" in capsys.readouterr().err
    assert not list(sandbox.glob("run-*"))


def test_occupied_port_prevents_preparation(tmp_path, monkeypatch, capsys):
    source, scans, sandbox = [
        tmp_path / name for name in ("source", "scans", "sandbox")
    ]
    source.mkdir()
    scans.mkdir()
    # Avoid requiring a built frontend in a clean CI checkout for this check.
    frontend = tmp_path / "fake-code/frontend/dist"
    frontend.mkdir(parents=True)
    (frontend / "index.html").write_text("built")
    monkeypatch.setitem(DEMO["main"].__globals__, "REPO", frontend.parents[1])
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        monkeypatch.setattr(
            sys,
            "argv",
            [
                "demo",
                "--scan-root",
                str(scans),
                "--source-results",
                str(source),
                "--sandbox-root",
                str(sandbox),
                "--port",
                str(listener.getsockname()[1]),
            ],
        )
        assert DEMO["main"]() == 1
    assert "Demo setup failed" in capsys.readouterr().err
    assert not list(sandbox.glob("run-*"))

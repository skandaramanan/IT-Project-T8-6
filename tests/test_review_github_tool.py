"""Offline checks for acceptance-tool safeguards; no GitHub or browser access."""

import argparse
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from review_support import git, setup_review

spec = importlib.util.spec_from_file_location(
    "review_github_test", Path(__file__).parents[1] / "scripts/review_github_test.py"
)
tool = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tool)


def workspace(tmp_path):
    _, settings = setup_review(tmp_path, with_git=True)
    tool.write_json(
        tmp_path / "manifest.json",
        {
            "repository": tool.REPOSITORY,
            "branch": "review-data",
            "local": True,
            "remote": str(tmp_path / "remote.git"),
            "sources": [],
            "real_sample": False,
            "code_sha": git(tool.CODE, "rev-parse", "HEAD"),
            "seed_sha": git(settings.data_checkout, "rev-parse", "HEAD"),
        },
    )
    return tool.Run(tmp_path), settings


def test_prepare_refuses_existing_directory_before_any_git_operation(tmp_path):
    marker = tmp_path / "keep.txt"
    marker.write_text("keep")
    with pytest.raises(RuntimeError, match="Workspace must be new"):
        tool.prepare(argparse.Namespace(workspace=tmp_path))
    assert marker.read_text() == "keep"


def test_clone_refuses_replaced_branch_without_seed_ancestor(tmp_path):
    run, settings = workspace(tmp_path)
    git(settings.data_checkout, "checkout", "--orphan", "replacement")
    git(settings.data_checkout, "commit", "-m", "Unrelated history")
    git(settings.data_checkout, "push", "--force", "origin", "replacement:review-data")
    with pytest.raises(RuntimeError):
        run.clone("refused")


def test_failed_push_scope_restores_transport_on_exception(tmp_path):
    run, settings = workspace(tmp_path)
    server = SimpleNamespace(checkout=settings.data_checkout)
    original = git(server.checkout, "remote", "get-url", "--push", "origin")
    with pytest.raises(ValueError), run.failed_push(server):
        assert git(server.checkout, "remote", "get-url", "--push", "origin") != original
        raise ValueError("scenario interrupted")
    assert git(server.checkout, "remote", "get-url", "--push", "origin") == original


def test_report_records_failed_assertion_without_remote_or_secret_output(tmp_path):
    run, _ = workspace(tmp_path)

    def failure():
        raise RuntimeError("Expected local-save success")

    assert not run.scenario("save", failure)
    report = json.loads((run.directory / "report.json").read_text())
    assert report["results"][0]["status"] == "failed"
    assert report["results"][0]["error"] == "Expected local-save success"


def test_verify_refuses_unrelated_application_commit(tmp_path):
    run, settings = workspace(tmp_path)
    (settings.data_checkout / "unrelated.txt").write_text("unexpected")
    git(settings.data_checkout, "add", ".")
    git(settings.data_checkout, "commit", "-m", "Unexpected application commit")
    git(settings.data_checkout, "push", "origin", "review-data")
    with pytest.raises(RuntimeError, match="unexpected paths"):
        run.verify()


def test_repin_validates_existing_data_and_preserves_remote_history(
    tmp_path, monkeypatch
):
    workspace(tmp_path)
    path = tmp_path / "manifest.json"
    manifest = json.loads(path.read_text())
    manifest["code_sha"] = git(tool.CODE, "rev-parse", "HEAD^")
    tool.write_json(path, manifest)
    original_git = tool.git
    monkeypatch.setattr(
        tool,
        "git",
        lambda where, *args: (
            ""
            if where == tool.CODE and args == ("status", "--porcelain")
            else original_git(where, *args)
        ),
    )
    before = git(tmp_path / "remote.git", "rev-parse", "review-data")
    tool.repin(tmp_path)
    updated = json.loads(path.read_text())
    assert updated["code_sha"] == git(tool.CODE, "rev-parse", "HEAD")
    assert updated["revision_history"][0]["previous_code_sha"] == manifest["code_sha"]
    assert updated["seed_sha"] == manifest["seed_sha"]
    assert git(tmp_path / "remote.git", "rev-parse", "review-data") == before

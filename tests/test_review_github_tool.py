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
    git(settings.data_checkout, "branch", "-m", tool.BRANCH)
    git(settings.data_checkout, "push", "origin", tool.BRANCH)
    tool.write_json(
        tmp_path / "manifest.json",
        {
            "repository": tool.REPOSITORY,
            "branch": tool.BRANCH,
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
    git(
        settings.data_checkout,
        "push",
        "--force",
        "origin",
        f"replacement:{tool.BRANCH}",
    )
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


def test_report_does_not_claim_acceptance_after_first_success(tmp_path):
    run, _ = workspace(tmp_path)
    run.manifest.update(local=False, real_sample=True)
    assert run.scenario("prepare-pending-fixtures", lambda: None)
    report = json.loads((run.directory / "report.json").read_text())
    assert not report["acceptance_complete"]


@pytest.mark.parametrize(
    "missing",
    ["real-sample", "browser-smoke", "original-source-hashes", "github-validation"],
)
def test_report_requires_every_acceptance_phase(tmp_path, missing):
    run, _ = workspace(tmp_path)
    run.manifest.update(local=False, real_sample=True)
    names = [name for name, _ in tool.api_scenarios(run)] + [
        "browser-smoke",
        "original-source-hashes",
        "github-validation",
    ]
    run.results = [
        {"name": name, "status": "passed"} for name in names if name != missing
    ]
    run.report()
    report = json.loads((run.directory / "report.json").read_text())
    assert not report["acceptance_complete"]

    run.results.append({"name": missing, "status": "passed"})
    run.report()
    report = json.loads((run.directory / "report.json").read_text())
    assert report["acceptance_complete"]


@pytest.mark.parametrize(
    "local,real_sample,status",
    [
        (True, True, "passed"),
        (False, False, "passed"),
        (False, True, "failed"),
        (False, True, "blocked"),
        (False, True, "not_run"),
    ],
)
def test_report_requires_live_real_sample_and_success(
    tmp_path, local, real_sample, status
):
    run, _ = workspace(tmp_path)
    run.manifest.update(local=local, real_sample=real_sample)
    run.results = [
        {"name": name, "status": "passed"} for name, _ in tool.api_scenarios(run)
    ] + [
        {"name": "browser-smoke", "status": "passed"},
        {"name": "original-source-hashes", "status": "passed"},
        {"name": "github-validation", "status": status},
    ]
    run.report()
    report = json.loads((run.directory / "report.json").read_text())
    assert not report["acceptance_complete"]


def test_verify_refuses_unrelated_application_commit(tmp_path):
    run, settings = workspace(tmp_path)
    (settings.data_checkout / "unrelated.txt").write_text("unexpected")
    git(settings.data_checkout, "add", ".")
    git(settings.data_checkout, "commit", "-m", "Unexpected application commit")
    git(settings.data_checkout, "push", "origin", tool.BRANCH)
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
    before = git(tmp_path / "remote.git", "rev-parse", tool.BRANCH)
    tool.repin(tmp_path)
    updated = json.loads(path.read_text())
    assert updated["code_sha"] == git(tool.CODE, "rev-parse", "HEAD")
    assert updated["revision_history"][0]["previous_code_sha"] == manifest["code_sha"]
    assert updated["seed_sha"] == manifest["seed_sha"]
    assert git(tmp_path / "remote.git", "rev-parse", tool.BRANCH) == before


@pytest.mark.parametrize(
    "push_urls", [[], ["/old/push"], ["/old/first", "/old/second"]]
)
def test_failed_push_preserves_all_explicit_push_urls(tmp_path, push_urls):
    run, settings = workspace(tmp_path)
    server = SimpleNamespace(checkout=settings.data_checkout)
    for url in push_urls:
        git(server.checkout, "config", "--add", "remote.origin.pushurl", url)
    with pytest.raises(ValueError), run.failed_push(server):
        assert git(
            server.checkout, "remote", "get-url", "--push", "--all", "origin"
        ) == str(run.directory / "missing-remote.git")
        raise ValueError("interrupted")
    effective = git(server.checkout, "remote", "get-url", "--push", "--all", "origin")
    assert effective.splitlines() == (push_urls or [str(tmp_path / "remote.git")])


def test_production_workspace_is_refused_before_git_or_mutation(tmp_path, monkeypatch):
    tool.write_json(
        tmp_path / "manifest.json",
        {"repository": tool.REPOSITORY, "branch": "review-data"},
    )

    def unexpected(*args, **kwargs):
        pytest.fail("A production workspace must be refused before any operation")

    monkeypatch.setattr(tool, "git", unexpected)
    with pytest.raises(RuntimeError, match="Production review-data"):
        tool.Run(tmp_path, verify_revision=False)  # repin cannot bypass isolation
    assert list(tmp_path.iterdir()) == [tmp_path / "manifest.json"]


def test_prepare_requires_scan_root_before_provisioning(tmp_path, monkeypatch):
    root = tmp_path / "new-workspace"

    def unexpected(*args, **kwargs):
        pytest.fail("Missing scan root must be rejected before Git operations")

    monkeypatch.setattr(tool, "git", unexpected)
    with pytest.raises(RuntimeError, match="--scan-root is required"):
        tool.prepare(
            argparse.Namespace(
                workspace=root, local=True, synthetic_only=False, scan_root=None
            )
        )
    assert not root.exists()


def test_synthetic_preparation_only_pushes_acceptance_branch(tmp_path):
    root = tmp_path / "new-workspace"
    tool.prepare(
        argparse.Namespace(
            workspace=root, local=True, synthetic_only=True, scan_root=None
        )
    )
    manifest = json.loads((root / "manifest.json").read_text())
    assert manifest["branch"] == "review-data-acceptance"
    assert (
        git(root / "remote.git", "for-each-ref", "--format=%(refname)", "refs/heads")
        == "refs/heads/review-data-acceptance"
    )
    assert git(root / "remote.git", "rev-parse", tool.BRANCH) == manifest["seed_sha"]


@pytest.mark.parametrize("existing", [False, True])
def test_browser_failure_restores_both_environment_variables(
    tmp_path, monkeypatch, existing
):
    keys = ("REVIEW_TEST_WORKSPACE", "REVIEW_TEST_PYTHON")
    for key in keys:
        if existing:
            monkeypatch.setenv(key, f"original-{key}")
        else:
            monkeypatch.delenv(key, raising=False)
    with pytest.raises(ValueError), tool.browser_environment(tmp_path):
        assert tool.os.environ["REVIEW_TEST_WORKSPACE"] == str(tmp_path)
        assert tool.os.environ["REVIEW_TEST_PYTHON"] == tool.sys.executable
        raise ValueError("browser failure")
    for key in keys:
        assert tool.os.environ.get(key) == (f"original-{key}" if existing else None)


def test_manual_commands_select_acceptance_branch(tmp_path, monkeypatch, capsys):
    workspace(tmp_path)
    monkeypatch.setattr(
        tool.sys, "argv", ["review_github_test.py", "manual", str(tmp_path)]
    )
    assert tool.main() == 0
    commands = capsys.readouterr().out.splitlines()
    assert len(commands) == 2
    assert all("--data-branch review-data-acceptance" in line for line in commands)

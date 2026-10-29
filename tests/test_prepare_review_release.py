"""Release bundles require an explicit override for uncommitted content."""

import hashlib
import importlib.util
import json
import subprocess
from pathlib import Path
from zipfile import ZipFile

import pytest

MODULE = Path(__file__).parents[1] / "scripts/prepare_review_release.py"
spec = importlib.util.spec_from_file_location("prepare_review_release", MODULE)
release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)


@pytest.fixture
def source(tmp_path, monkeypatch):
    repo = tmp_path / "source"
    repo.mkdir()
    for directory in ["backend", "schema", "scripts", "docs", "frontend/dist", "tests"]:
        (repo / directory).mkdir(parents=True, exist_ok=True)
    for name in [
        "frontend/dist/index.html",
        "pyproject.toml",
        "uv.lock",
        ".python-version",
        "README.md",
        "THIRD_PARTY_NOTICES.md",
        "tests/review_support.py",
    ]:
        (repo / name).write_text("fixture\n")
    subprocess.run(["git", "init", str(repo)], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(repo),
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.com",
            "commit",
            "-m",
            "fixture",
        ],
        check=True,
        capture_output=True,
    )
    monkeypatch.setattr(release, "REPO", repo)
    return repo


def test_clean_release_records_revision_and_contents(source, tmp_path):
    output = tmp_path / "release.zip"
    manifest = release.prepare_release(output)
    assert manifest["working_tree_dirty"] is False
    assert (
        manifest["base_revision"]
        == subprocess.check_output(
            ["git", "-C", str(source), "rev-parse", "HEAD"], text=True
        ).strip()
    )
    with ZipFile(output) as archive:
        assert (
            json.loads(archive.read("survey-review/RELEASE-MANIFEST.json")) == manifest
        )
        assert archive.read("survey-review/README.md") == b"fixture\n"
        notice = archive.read("survey-review/THIRD_PARTY_NOTICES.md")
        assert notice == (source / "THIRD_PARTY_NOTICES.md").read_bytes()
        assert (
            manifest["files"]["THIRD_PARTY_NOTICES.md"]
            == hashlib.sha256(notice).hexdigest()
        )


@pytest.mark.parametrize("name", ["README.md", "untracked.txt"])
def test_dirty_requires_override_and_manifest_records_it(source, tmp_path, name):
    (source / name).write_text("uncommitted\n")
    output = tmp_path / "release.zip"
    with pytest.raises(ValueError, match="--allow-dirty"):
        release.prepare_release(output)
    assert not output.exists()
    assert release.prepare_release(output, allow_dirty=True)["working_tree_dirty"]

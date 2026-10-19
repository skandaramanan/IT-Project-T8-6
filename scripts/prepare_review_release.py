"""Package source, locked dependencies and the matching built reviewer for Windows.

Run npm ci && npm run build in frontend immediately before this helper. The
operator installs Python dependencies with uv; Node is needed only by the builder.
No scans, extracted results, credentials or virtual environment are included.
"""

import argparse
import hashlib
import json
import subprocess
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

REPO = Path(__file__).resolve().parents[1]


def prepare_release(output: Path, *, allow_dirty: bool = False):
    output = output.resolve()
    if output.exists() or output.is_relative_to(REPO):
        raise ValueError("Choose a new ZIP path outside the source checkout")
    if not (REPO / "frontend/dist/index.html").is_file():
        raise ValueError("Build frontend/dist before preparing a release")
    required = [
        "backend",
        "schema",
        "scripts",
        "docs",
        "frontend/dist",
        "pyproject.toml",
        "uv.lock",
        ".python-version",
        "README.md",
        "tests/review_support.py",
    ]
    files = []
    for name in required:
        path = REPO / name
        files.extend(path.rglob("*") if path.is_dir() else [path])
    files = sorted(
        path
        for path in files
        if path.is_file()
        and not path.is_symlink()
        and "__pycache__" not in path.parts
        and path.suffix not in {".pyc", ".pyo"}
    )
    revision = subprocess.check_output(
        ["git", "-C", str(REPO), "rev-parse", "HEAD"], text=True
    ).strip()
    dirty = bool(
        subprocess.check_output(
            ["git", "-C", str(REPO), "status", "--porcelain"], text=True
        ).strip()
    )
    if dirty and not allow_dirty:
        raise ValueError("Working tree is dirty; commit changes or pass --allow-dirty")
    manifest = {
        "base_revision": revision,
        "working_tree_dirty": dirty,
        "files": {
            str(path.relative_to(REPO)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in files
        },
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(output, "x", ZIP_DEFLATED) as archive:
        for path in files:
            archive.write(path, Path("survey-review") / path.relative_to(REPO))
        archive.writestr(
            "survey-review/RELEASE-MANIFEST.json", json.dumps(manifest, indent=2) + "\n"
        )
    print(output)
    print(f"SHA-256: {hashlib.sha256(output.read_bytes()).hexdigest()}")
    print(
        "Windows/operator acceptance is still required. See docs/review-windows-acceptance.md."
    )
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument(
        "--allow-dirty", action="store_true", help="Package uncommitted changes"
    )
    args = parser.parse_args()
    try:
        prepare_release(args.output, allow_dirty=args.allow_dirty)
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        parser.error(str(error))

"""Smoke test: proves pytest runs and the interpreter is the pinned one."""

import sys
from pathlib import Path


def test_python_matches_pinned_version():
    pinned = (Path(__file__).parent.parent / ".python-version").read_text().strip()
    running = f"{sys.version_info.major}.{sys.version_info.minor}"
    assert running == pinned, f"running Python {running}, .python-version pins {pinned}"

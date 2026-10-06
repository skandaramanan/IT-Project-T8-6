"""The package never imports the calibration harness (D024).

benchmark/ is on pytest's path, so a stray ``from scoring import ...`` inside
backend/survey/ would pass every test here and then fail for anyone who
installed the package without the harness.
"""

import ast
from pathlib import Path

ROOT = Path(__file__).parent.parent
HARNESS = {p.stem for p in (ROOT / "benchmark").glob("*.py")} | {"benchmark"}


def test_survey_never_imports_benchmark():
    offenders = []
    for path in sorted((ROOT / "backend" / "survey").rglob("*.py")):
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0:
                names = [node.module]
            else:
                continue
            offenders += [
                f"{path.relative_to(ROOT)}:{node.lineno} imports {name}"
                for name in names
                if name.split(".")[0] in HARNESS
            ]
    assert not offenders, "\n".join(offenders)

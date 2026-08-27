"""Entry point for the structure pipeline: ``uv run main.py [step] [options]``.

This exists so the pipeline runs without a PYTHONPATH in front of it. The
project isn't installed as a package (pyproject's ``package = false``), so
``src`` is on the path for pytest and for nothing else; four lines here beat
asking everyone to remember an environment variable.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

from structure.cli import main

if __name__ == "__main__":
    main()

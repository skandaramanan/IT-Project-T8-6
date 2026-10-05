"""Prints the page features segmentation.py classifies on, one row per
fixture image, so the thresholds in backend/survey/segmentation/segmenter.py can be
checked or re-tuned against tests/fixtures/ by eye.

Run from the repo root: python benchmark/calibrate_segmentation.py
"""

from __future__ import annotations

from pathlib import Path

from survey.segmentation.segmenter import _page_features

FIXTURES = Path(__file__).parent.parent / "tests" / "fixtures"
RECORDS = [f"r{n:02d}" for n in range(1, 6)]
ROLES = ["survey-front", "survey-back", "coding-front", "coding-back"]


def main() -> None:
    for record in RECORDS:
        for role in ROLES:
            path = FIXTURES / f"{record}-{role}.jpg"
            f = _page_features(path)
            print(
                f"{record}-{role:14s} ink={f.ink_fraction:.4f}"
                f"  ruled_rows={f.ruled_rows:3d}  ruled_cols={f.ruled_cols:3d}"
            )


if __name__ == "__main__":
    main()

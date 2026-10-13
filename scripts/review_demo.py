"""Create a synthetic review demo and a temporary local Git remote.

Usage: uv run python scripts/review_demo.py <new-empty-directory>
No live survey data, extraction, GitHub access, or credentials are used.
"""

import argparse
import json
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw

from survey.extraction.record import build_record


def git(where, *args):
    subprocess.run(["git", "-C", str(where), *args], check=True)


def create_demo(root: Path):
    root = root.resolve()
    if root.exists() and any(root.iterdir()):
        raise ValueError(
            "Choose a new or empty directory; existing work will not be replaced"
        )
    root.mkdir(parents=True, exist_ok=True)
    checkout = root / "data checkout"
    results = checkout / "results"
    results.mkdir(parents=True)
    scan_dir = root / "scans" / "demo"
    scan_dir.mkdir(parents=True)
    records = []
    pages = []
    for index, value in [(1, "04"), (2, "12")]:
        record = build_record(
            {
                "Municipality": "27",
                "Number of Dwelling": "6",
                "Number of Household": str(index),
                "Weekly Rent": value,
                "Garden": "1",
            },
            region="demo",
            batch="synthetic.pdf",
            image="synthetic.pdf",
            page=index,
        )
        records.append(record)
        image = Image.new("RGB", (1200, 800), "#f0e2b8")
        draw = ImageDraw.Draw(image)
        for y, text in [
            (50, "SYNTHETIC DEMO / NOT A REAL TRANSCRIPTION"),
            (150, f"Coding card: household {index} / original page {index}"),
            (250, f"Weekly rent: {value}"),
            (350, "Garden: 1"),
        ]:
            draw.text((50, y), text, fill="black", font_size=30)
        pages.append(image)
    record = records[0]
    record["dwelling"]["households"].append(records[1]["dwelling"]["households"][0])
    (results / "demo.jsonl").write_text(json.dumps(record) + "\n", encoding="utf-8")
    pages[0].save(scan_dir / "synthetic.pdf", save_all=True, append_images=pages[1:])
    pointers = [
        (1, "/dwelling/households/0/coding/weekly_rent"),
        (2, "/dwelling/households/1/coding/weekly_rent"),
        (1, "/dwelling/house/garden"),
    ]
    (root / "flags.jsonl").write_text(
        "".join(
            json.dumps(
                {
                    "region": "demo",
                    "pdf": "synthetic.pdf",
                    "page": page,
                    "field_path": pointer,
                    "reason": "Synthetic integration test",
                }
            )
            + "\n"
            for page, pointer in pointers
        ),
        encoding="utf-8",
    )
    remote = root / "remote.git"
    git(root, "init", "--bare", str(remote))
    git(checkout, "init", "-b", "review-data")
    git(checkout, "config", "user.name", "Synthetic Demo")
    git(checkout, "config", "user.email", "demo@example.invalid")
    git(checkout, "add", "results/demo.jsonl")
    git(checkout, "commit", "-m", "Seed synthetic demo")
    git(checkout, "remote", "add", "origin", str(remote))
    git(checkout, "push", "-u", "origin", "review-data")
    print("\nLaunch from the code checkout (quoted paths work with spaces):")
    print(
        f'uv run survey review --scan-root "{root / "scans"}" --data-checkout "{checkout}" --flags "{root / "flags.jsonl"}" --cache "{root / "cache"}" --open-browser'
    )
    return root


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    args = parser.parse_args()
    try:
        create_demo(args.directory)
    except ValueError as error:
        parser.error(str(error))

"""Build IT-125 offline into an isolated directory; never modify either input.

uv run python scripts/merge_scored_results.py --output data/it125-staged
"""

import argparse
from pathlib import Path

from survey.merge_runs import merge_dataset


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--primary", type=Path, default=Path("results"))
    parser.add_argument(
        "--secondary", type=Path, default=Path("results/qwen2.5-vl-server-2000000px")
    )
    parser.add_argument("--gemini-cache", type=Path, default=Path("data/runs"))
    parser.add_argument(
        "--qwen-cache",
        type=Path,
        default=Path("data/it124-review-20261017/handoff/data/runs"),
    )
    parser.add_argument(
        "--excluded", type=Path, default=Path("docs/runs/it124-excluded-sources.json")
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    rows = merge_dataset(
        args.primary,
        args.secondary,
        args.gemini_cache,
        args.qwen_cache,
        args.output,
        args.excluded,
    )
    print(
        f"Staged {sum(r['dwellings'] for r in rows)} dwellings / {sum(r['coding_cards'] for r in rows)} coding cards in {args.output}"
    )


if __name__ == "__main__":
    main()

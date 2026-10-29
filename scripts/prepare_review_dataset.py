"""Prepare a separate per-card review dataset from retained primary artifacts.

No extraction, rescoring or publication occurs. Example:
  uv run python scripts/prepare_review_dataset.py --previous results --output /tmp/review-staging --cache data/runs
"""

import argparse
from pathlib import Path

from survey.review.prepare import prepare_dataset


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--previous", type=Path, default=Path("results"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cache", type=Path)
    parser.add_argument(
        "--cache-name",
        help="Extractor folder under each region's cache (default: the Gemini one); "
        "the Qwen export needs qwen2.5-vl-server-2000000px/qwen-qwen2.5-vl-7b-q6_k",
    )
    parser.add_argument(
        "--field-evidence",
        type=Path,
        help="Existing source/field-specific measured confidence JSON; never recomputed",
    )
    args = parser.parse_args()
    try:
        report = prepare_dataset(
            args.previous,
            args.output,
            args.cache,
            args.field_evidence,
            args.cache_name,
        )
    except (ValueError, OSError) as error:
        parser.error(str(error))
    print(
        f"Prepared {report['cards']} cards; {len(report['missing_fields'])} missing per-card fields; {report['queued_fields']} queued fields. Production seed unchanged."
    )


if __name__ == "__main__":
    main()

"""The performance helper reviews copies without changing source data or Git."""

import runpy
from pathlib import Path

from review_support import setup_review

SCRIPT = Path(__file__).parents[1] / "scripts/review_benchmark.py"


def test_benchmark_uses_disposable_data_and_reports_excluded_empty_files(tmp_path):
    service, settings = setup_review(tmp_path)
    source = service.store.directory
    (source / "empty.jsonl").write_text("")
    before = {path.name: path.read_bytes() for path in source.iterdir()}
    metrics = runpy.run_path(str(SCRIPT))["benchmark"](source, "demo", 1)
    assert metrics["regions"] == metrics["dwellings"] == 1
    assert metrics["excluded_empty_files"] == ["empty.jsonl"]
    assert metrics["remote"] == "local bare Git"
    assert len(metrics["accept_s"]) == 1
    assert metrics["share_max_lock_hold_s"] <= metrics["share_total_lock_hold_s"]
    assert {path.name: path.read_bytes() for path in source.iterdir()} == before
    assert not (settings.data_checkout / ".git").exists()

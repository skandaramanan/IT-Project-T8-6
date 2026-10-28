"""Measure local review startup/saves/sharing on disposable copies, with scans stubbed.

No model calls or network remote: source JSONL stays untouched. This selects all
supported coding fields for a load test, not a production review-routing rule.
"""

import argparse
import json
import subprocess
import tempfile
from pathlib import Path
from threading import local
from time import perf_counter
from unittest.mock import patch

from fastapi.testclient import TestClient

from survey.records import Reference
from survey.review.api import Settings, create_app
from survey.review.fields import field_pointers
from survey.review.prepare import prepare_records

REPO = Path(__file__).resolve().parents[1]


class StubScans:
    def __init__(self, *args):
        pass

    def probe(self, ref):
        pass

    def get_scan(self, ref):
        return REPO / "tests/fixtures/r01-coding-front.jpg"


class ObservedLock:
    """Measure outermost lock holds, excluding time waiting to acquire it."""

    def __init__(self, lock):
        self.lock, self.thread = lock, local()
        self.maximum = self.total = 0

    def __enter__(self):
        self.lock.acquire()
        depth = getattr(self.thread, "depth", 0)
        if not depth:
            self.thread.started = perf_counter()
        self.thread.depth = depth + 1
        return self

    def __exit__(self, *args):
        self.thread.depth -= 1
        if not self.thread.depth:
            elapsed = perf_counter() - self.thread.started
            self.maximum = max(self.maximum, elapsed)
            self.total += elapsed
        self.lock.release()


def record_flags(record):
    for index, household in enumerate(record["dwelling"]["households"]):
        cards = [c for c in household.get("cards", []) if c["role"] == "coding-front"]
        if not cards:
            continue
        card = cards[0]
        for _, pointer, group in field_pointers(
            index, review=record["schema_version"] == "0.7.0", include_shared=index == 0
        ):
            if group == "front":
                continue
            node = record
            try:
                for part in pointer.split("/")[1:]:
                    node = node[int(part)] if isinstance(node, list) else node[part]
            except (KeyError, IndexError, TypeError):
                continue
            if node.get("source", "coding-front") == "coding-front":
                yield Reference(
                    record["region"], card["image"], card.get("page"), pointer
                )


def benchmark(source: Path, region: str, iterations: int) -> dict:
    if iterations < 1:
        raise ValueError("Iterations must be positive")
    measurements = {"scan_rendering": "stubbed", "remote": "local bare Git"}
    with tempfile.TemporaryDirectory(prefix="survey-review-benchmark-") as directory:
        root = Path(directory)
        checkout = root / "data"
        results = checkout / "results"
        results.mkdir(parents=True)
        refs, skipped, dwellings = [], [], 0
        for path in sorted(source.glob("*.jsonl")):
            lines = [
                line
                for line in path.read_text(encoding="utf-8-sig").splitlines()
                if line.strip()
            ]
            if not lines:
                skipped.append(path.name)
                continue
            rows = [json.loads(line) for line in lines]
            if any(row["schema_version"] != "0.7.0" for row in rows):
                rows, _ = prepare_records(rows)
            (results / path.name).write_text(
                "".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8"
            )
            for row in rows:
                refs.extend(record_flags(row))
                dwellings += 1
        measurements.update(
            regions=len(list(results.glob("*.jsonl"))),
            dwellings=dwellings,
            flags=len(refs),
            excluded_empty_files=skipped,
        )
        flags = root / "flags.jsonl"
        flags.write_text(
            "".join(
                json.dumps(
                    {
                        "region": r.region,
                        "pdf": r.pdf,
                        "page": r.page,
                        "field_path": r.field_path,
                    }
                )
                + "\n"
                for r in refs
            ),
            encoding="utf-8",
        )

        def git(*args):
            subprocess.run(
                ["git", "-C", str(checkout), *args], check=True, capture_output=True
            )

        git("init", "--bare", str(root / "remote.git"))
        git("init", "-b", "review-data")
        git("config", "user.name", "Disposable benchmark")
        git("config", "user.email", "benchmark@example.invalid")
        git("add", "results")
        git("commit", "-m", "Seed copied results")
        git("remote", "add", "origin", str(root / "remote.git"))
        git("push", "-u", "origin", "review-data")
        settings = Settings(root, checkout, flags, root / "cache", sync_interval=3600)
        started = perf_counter()
        with (
            patch("survey.review.api.LocalScanSource", StubScans),
            TestClient(
                create_app(settings), base_url="http://127.0.0.1:8765"
            ) as client,
        ):
            measurements["startup_s"] = round(perf_counter() - started, 3)
            health = client.get("/api/health").json()
            if not health["ready"]:
                raise ValueError(f"Benchmark startup failed: {health['diagnostics']}")
            service = client.app.state.service
            targets = [
                ref
                for ref in service.references.values()
                if ref.region == region
                and ref.field_path.endswith("/weekly_rent")
                and service.store.current(ref)[0]
                .field.get("review", {})
                .get("state", "pending")
                == "pending"
            ]
            if len(targets) < iterations:
                raise ValueError(
                    "Selected region needs enough pending Weekly Rent fields"
                )
            client.post("/api/session", json={"name": "Disposable benchmark"})
            times = []
            for index, ref in enumerate(targets[:iterations]):
                item = service.item(ref.item_id)
                started = perf_counter()
                response = client.post(
                    f"/api/review-items/{ref.item_id}/decisions",
                    json={
                        "action": "accept",
                        "expected_version": item["version"],
                        "request_id": f"benchmark-{index}",
                    },
                )
                if response.status_code != 200:
                    raise ValueError(f"Benchmark save failed: {response.json()}")
                times.append(round(perf_counter() - started, 3))
            measurements["accept_s"] = times
            observed = ObservedLock(service.store.lock)
            service.store.lock = observed
            started = perf_counter()
            status = client.app.state.sync.sync(service.reindex_history)
            measurements["local_share_s"] = round(perf_counter() - started, 3)
            if status["state"] != "uploaded":
                raise ValueError(f"Benchmark share failed: {status}")
            measurements["share_max_lock_hold_s"] = round(observed.maximum, 3)
            measurements["share_total_lock_hold_s"] = round(observed.total, 3)
            started = perf_counter()
            for ref in refs:
                service.store.current(ref)
            measurements["resolve_all_flags_s"] = round(perf_counter() - started, 3)
        return measurements


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "results", type=Path, help="existing source results directory; read only"
    )
    parser.add_argument("--region", default="216418")
    parser.add_argument("--iterations", type=int, default=3)
    args = parser.parse_args()
    try:
        print(
            json.dumps(benchmark(args.results, args.region, args.iterations), indent=2)
        )
    except (ValueError, OSError, subprocess.SubprocessError) as error:
        parser.error(str(error))

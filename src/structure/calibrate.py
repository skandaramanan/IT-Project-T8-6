"""Does batching cost accuracy? Compare analyze runs of the same pages.

Batching is the only lever against a cap that counts requests rather than
pages, so the question is not whether it saves budget -- arithmetic settles
that -- but what it spends to do it. This compares one arm's analysis of a page
against the baseline arm's analysis of the same page, and reports where they
part company.

The measure is the one report.py already clusters on: the normalised set of
printed field labels. That is deliberate. A batch that scores 1.00 here does
not produce identical prose; it produces the same labels, which is all the
clustering downstream ever reads. Judging batching on anything the pipeline
does not use would be measuring a difference that costs nothing.

Nothing here calls the API. It reads two or more JSONL files written by
``analyze`` and is free to re-run.

    uv run main.py calibrate --arms results/calib_b1.jsonl results/calib_b5.jsonl
"""

from __future__ import annotations

import json
from pathlib import Path
from statistics import mean

from structure.report import jaccard, load_rows, normalise_label


def labels_of(row: dict) -> set[str]:
    return {normalise_label(f["label"]) for f in row["analysis"]["fields"]}


def read_arm(path: Path) -> dict:
    """One arm's rows plus what it cost. Billed cost is summed over distinct
    request_ids, because a batch's attempt count is repeated on each of its
    pages and must not be counted once per page."""
    ok, failed = load_rows(path)
    billed: dict[str, int] = {}
    for row in ok + failed:
        if row.get("request_id"):
            billed[row["request_id"]] = row.get("attempts", 1)
    return {
        "name": path.stem,
        "path": path,
        "ok": {row["card_id"]: row for row in ok},
        "failed": failed,
        "batch": max((row.get("batch", 1) for row in ok + failed), default=1),
        "requests": len(billed),
        "billed": sum(billed.values()),
        # Per-request wall time, not per-page: the same figure is stamped on
        # every page of a batch, so deduplicate by request before averaging.
        "seconds": {
            row["request_id"]: row["elapsed_s"]
            for row in ok + failed
            if row.get("request_id")
        },
    }


def compare(baseline: dict, arm: dict) -> dict:
    """Arm against baseline, over the pages both got right."""
    shared = sorted(set(baseline["ok"]) & set(arm["ok"]))
    scores, roles, titles, deltas = [], [], [], []
    by_role: dict[str, list[float]] = {}
    worst: list[tuple[float, str]] = []

    for card_id in shared:
        base, other = baseline["ok"][card_id], arm["ok"][card_id]
        base_labels, other_labels = labels_of(base), labels_of(other)
        score = jaccard(base_labels, other_labels)
        scores.append(score)
        worst.append((score, card_id))
        role = base["analysis"]["page_role"]
        by_role.setdefault(role, []).append(score)
        roles.append(role == other["analysis"]["page_role"])
        titles.append(
            normalise_label(base["analysis"].get("printed_title") or "")
            == normalise_label(other["analysis"].get("printed_title") or "")
        )
        deltas.append(len(other_labels) - len(base_labels))

    worst.sort()
    return {
        "arm": arm,
        "pages": len(shared),
        "jaccard": mean(scores) if scores else 0.0,
        "identical": sum(s == 1.0 for s in scores) / len(scores) if scores else 0.0,
        "role_agreement": mean(roles) if roles else 0.0,
        "title_agreement": mean(titles) if titles else 0.0,
        "field_delta": mean(deltas) if deltas else 0.0,
        "by_role": {role: mean(s) for role, s in sorted(by_role.items())},
        "worst": worst[:5],
        # Pages the baseline got and this arm did not: batching's other cost,
        # invisible in a score computed only over shared pages.
        "lost": sorted(set(baseline["ok"]) - set(arm["ok"])),
    }


def render(baseline: dict, comparisons: list[dict]) -> str:
    lines = [
        "# Batching calibration",
        "",
        (
            f"Baseline: `{baseline['path']}` -- {len(baseline['ok'])} pages ok, "
            f"{len(baseline['failed'])} failed, {baseline['billed']} requests billed."
        ),
        "",
        (
            "Label agreement is the mean Jaccard overlap of normalised printed "
            "field labels against the baseline's reading of the same page -- the "
            "same measure report.py clusters on."
        ),
        "",
        (
            "| arm | batch | pages | requests | pages/request | mean s/request | "
            "label agreement | identical | role agree | title agree | field delta |"
        ),
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for result in [{"arm": baseline, **compare(baseline, baseline)}, *comparisons]:
        arm = result["arm"]
        seconds = list(arm["seconds"].values())
        pages_ok = len(arm["ok"])
        lines.append(
            f"| `{arm['name']}` | {arm['batch']} | {pages_ok} | {arm['billed']} | "
            f"{pages_ok / arm['requests']:.1f} | "
            f"{mean(seconds) if seconds else 0:.0f} | "
            f"{result['jaccard']:.3f} | {result['identical']:.0%} | "
            f"{result['role_agreement']:.0%} | {result['title_agreement']:.0%} | "
            f"{result['field_delta']:+.1f} |"
        )

    lines += [
        "",
        "## By page role",
        "",
        (
            "Fronts are where the labels are; a batch that only holds up on "
            "near-blank backs has not been tested."
        ),
        "",
    ]
    roles = sorted({role for r in comparisons for role in r["by_role"]})
    lines.append("| arm | " + " | ".join(roles) + " |")
    lines.append("|---|" + "---:|" * len(roles))
    for result in comparisons:
        cells = [f"{result['by_role'].get(role, float('nan')):.3f}" for role in roles]
        lines.append(f"| `{result['arm']['name']}` | " + " | ".join(cells) + " |")

    for result in comparisons:
        arm = result["arm"]
        lines += ["", f"## {arm['name']}", ""]
        if arm["failed"]:
            lines.append(
                f"- {len(arm['failed'])} page(s) failed: "
                + "; ".join(
                    sorted({str(r.get("error"))[:120] for r in arm["failed"]})[:3]
                )
            )
        if result["lost"]:
            lines.append(
                f"- {len(result['lost'])} page(s) the baseline read and this arm "
                f"did not: {', '.join(result['lost'][:6])}"
            )
        for score, card_id in result["worst"]:
            if score < 1.0:
                base = labels_of(baseline["ok"][card_id])
                other = labels_of(arm["ok"][card_id])
                lines.append(
                    f"- `{card_id}` {score:.2f} -- "
                    f"dropped {sorted(base - other)[:4] or 'nothing'}, "
                    f"added {sorted(other - base)[:4] or 'nothing'}"
                )
        if not lines[-1].startswith("-"):
            lines.append("- no disagreement with the baseline on any shared page")
    return "\n".join(lines) + "\n"


def run_calibration(arms: list[Path], out: Path) -> None:
    missing = [str(path) for path in arms if not path.exists()]
    if missing:
        raise SystemExit(f"no such results file(s): {', '.join(missing)}")
    if len(arms) < 2:
        raise SystemExit("--arms needs a baseline and at least one arm to compare")

    baseline, *rest = [read_arm(path) for path in arms]
    comparisons = [compare(baseline, arm) for arm in rest]
    report = render(baseline, comparisons)

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(report)
    print(report)
    print(f"Written to {out}")


def demo() -> None:
    """Self-check: a perfect arm scores 1.0, a lossy one scores less."""
    import tempfile

    def row(card_id, labels, role="coding-front", **extra):
        return {
            "card_id": card_id,
            "ok": True,
            "attempts": 1,
            "elapsed_s": 10.0,
            "analysis": {
                "page_role": role,
                "printed_title": "T",
                "fields": [{"label": label} for label in labels],
                "anomalies": [],
            },
            **extra,
        }

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        base, same, lossy = tmp / "b1.jsonl", tmp / "b5.jsonl", tmp / "b10.jsonl"
        pages = {"a": ["Name", "Age"], "b": ["Rent", "Rooms"]}
        for path, batch in ((base, 1), (same, 5), (lossy, 10)):
            path.write_text(
                "\n".join(
                    json.dumps(
                        row(
                            card_id,
                            labels[:1] if path is lossy else labels,
                            batch=batch,
                            request_id=f"{path.stem}-{card_id}",
                        )
                    )
                    for card_id, labels in pages.items()
                )
                + "\n"
            )

        arms = [read_arm(p) for p in (base, same, lossy)]
        assert compare(arms[0], arms[1])["jaccard"] == 1.0
        assert compare(arms[0], arms[1])["identical"] == 1.0
        assert compare(arms[0], arms[2])["jaccard"] == 0.5  # 1 of 2 labels kept
        assert compare(arms[0], arms[2])["field_delta"] == -1.0
        assert arms[2]["requests"] == 2 and arms[2]["batch"] == 10
        # A page only the baseline read must show up as lost, not as agreement.
        (tmp / "b5.jsonl").write_text(json.dumps(row("a", ["Name", "Age"])) + "\n")
        assert compare(arms[0], read_arm(same))["lost"] == ["b"]
        assert "Batching calibration" in render(arms[0], [compare(arms[0], arms[2])])
    print("calibrate demo ok")


if __name__ == "__main__":
    demo()

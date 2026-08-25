"""Pass 2: turn per-page observations into structures, and name the exceptions.

Clustering is deliberately not a plain hash of the model's field list. Two scans
of the same printed form differ by a comma or a dropped abbreviation, and an
exact hash turns that into a separate "structure" -- a variant count made of
transcription jitter rather than archival fact. So: labels are normalised, the
normalised set is hashed for exact grouping, and then clusters whose label sets
overlap by at least --merge-threshold are folded together. Every merge is
reported, so a merge that shouldn't have happened is visible rather than
buried.

The 0.8 default is measured, not guessed. On the first 354 pages the model
transcribed the same printed form two ways -- "children of h or wife" plus
"dead"/"living"/"total" as separate labels on one card, "children of h or wife
dead" as one label on the next -- which costs about five labels each way out of
sixty, i.e. a jaccard around 0.85. Sweeping the threshold put a knee right
there: off-canonical cards ran 40% at 0.95, 15% at 0.85, 4% at 0.8, and 0.75
and 0.70 came out identical to each other, so the grouping is stable below the
knee rather than dissolving. Re-run ``--sweep`` once the full corpus is in; a
default fitted to two units is a starting point, not a finding.

Cards are compared within a page role, never across. A coding front and a
survey back are not variants of each other, and pooling them makes the biggest
cluster meaningless.

Also checks the four-page record cycle. tests/fixtures/README.md establishes the
repeating unit as survey front, survey back, coding front, coding back, and
22 of 44 unit PDFs have page counts that don't divide by four -- so this finds
where each unit actually departs from the cycle, which is the structural
question the page counts raise but can't answer.

Run via the CLI: ``uv run main.py report`` (see structure/cli.py).
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image

from structure.inventory import open_unit, page_image

DEFAULT_RESULTS = Path("results/pages.jsonl")
DEFAULT_OUT = Path("results")
RECORD_CYCLE = ("survey-front", "survey-back", "coding-front", "coding-back")
# The two printed fronts, numeric card first: coding-front is the coded card
# (counts, grades, totals), survey-front the text one. Reverses are excluded on
# purpose -- see export_reference_cards.
FRONT_ROLES = ("coding-front", "survey-front")


def normalise_label(label: str) -> str:
    """Collapse the differences that are transcription noise, keep the ones that
    are a different field. Case, surrounding punctuation, and whitespace go;
    words and digits stay."""
    text = re.sub(r"[^a-z0-9 ]+", " ", str(label).lower())
    return " ".join(text.split())


def fingerprint(role: str, labels: set[str]) -> str:
    joined = "\n".join(sorted(labels))
    return hashlib.sha1(f"{role}\n{joined}".encode()).hexdigest()[:8]


def jaccard(left: set[str], right: set[str]) -> float:
    if not left and not right:
        return 1.0
    return len(left & right) / len(left | right)


@dataclass
class Cluster:
    cluster_id: str
    role: str
    labels: set[str]
    cards: list[dict] = field(default_factory=list)
    merged: list[str] = field(default_factory=list)

    @property
    def size(self) -> int:
        return len(self.cards)


def load_rows(results_path: Path) -> tuple[list[dict], list[dict]]:
    """(successful rows, failed rows), last row per card id wins -- a rerun
    appends a fresh attempt rather than editing the old line."""
    latest: dict[str, dict] = {}
    with results_path.open() as file:
        for line in file:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            latest[row["card_id"]] = row
    rows = sorted(latest.values(), key=lambda r: r["card_id"])
    return [r for r in rows if r.get("ok")], [r for r in rows if not r.get("ok")]


def cluster_rows(rows: list[dict], threshold: float) -> list[Cluster]:
    exact: dict[str, Cluster] = {}
    for row in rows:
        role = row["analysis"]["page_role"]
        labels = {
            normalise_label(f["label"])
            for f in row["analysis"]["fields"]
            if normalise_label(f["label"])
        }
        key = fingerprint(role, labels)
        cluster = exact.setdefault(
            key, Cluster(cluster_id=key, role=role, labels=labels)
        )
        cluster.cards.append(row)

    # Greedy merge, biggest first: a small cluster joins the largest one it is
    # close enough to. ponytail: O(n_clusters^2); n_clusters is in the hundreds
    # at worst, so a real nearest-neighbour index would be pure ceremony.
    merged: list[Cluster] = []
    for cluster in sorted(exact.values(), key=lambda c: c.size, reverse=True):
        host = next(
            (
                other
                for other in merged
                if other.role == cluster.role
                and jaccard(other.labels, cluster.labels) >= threshold
            ),
            None,
        )
        if host is None:
            merged.append(cluster)
        else:
            host.cards.extend(cluster.cards)
            host.merged.append(f"{cluster.cluster_id}({cluster.size})")
    return sorted(merged, key=lambda c: c.size, reverse=True)


def label_frequency(cluster: Cluster) -> list[tuple[str, int]]:
    counts: Counter[str] = Counter()
    for card in cluster.cards:
        counts.update(
            {
                normalise_label(f["label"])
                for f in card["analysis"]["fields"]
                if normalise_label(f["label"])
            }
        )
    return counts.most_common()


def rank_anomalies(clusters: list[Cluster]) -> list[dict]:
    """Every distinct anomaly the model reported, rarest first.

    Rarity is the signal worth a human's time: "punch holes at top edge" on
    9,000 cards is how the paper was filed, the same phrasing on three cards is
    something about those three. Grouping is by normalised text, so two ways of
    saying the same thing stay separate -- deliberately, since collapsing them
    would need a similarity call this file has no business making about prose.
    """
    counts: Counter[tuple[str, str]] = Counter()
    examples: dict[tuple[str, str], list[str]] = defaultdict(list)
    role_totals: Counter[str] = Counter()
    for cluster in clusters:
        role_totals[cluster.role] += cluster.size
        for card in cluster.cards:
            for anomaly in card["analysis"].get("anomalies") or []:
                key = (cluster.role, normalise_label(anomaly))
                counts[key] += 1
                if len(examples[key]) < 5:
                    examples[key].append(card["card_id"])

    return [
        {
            "page_role": role,
            "anomaly": text,
            "cards": count,
            "share_of_role": f"{count / role_totals[role]:.2%}",
            "example_cards": " ".join(examples[role, text]),
        }
        for (role, text), count in sorted(counts.items(), key=lambda item: item[1])
    ]


def sweep_thresholds(rows: list[dict]) -> None:
    """Print cluster counts across a range of thresholds, so the choice of
    --merge-threshold is a reading off a curve rather than a preference."""
    print(f"{len(rows)} pages\n")
    print(f"{'thresh':>7} {'clusters':>9} {'off-canonical':>15}  biggest per role")
    for threshold in (0.95, 0.9, 0.85, 0.8, 0.75, 0.7, 0.6):
        clusters = cluster_rows(rows, threshold)
        dominant: dict[str, Cluster] = {}
        for cluster in clusters:
            dominant.setdefault(cluster.role, cluster)
        off = sum(c.size for c in clusters if c is not dominant[c.role])
        tops = " ".join(f"{r}:{c.size}" for r, c in sorted(dominant.items()))
        print(
            f"{threshold:>7} {len(clusters):>9} {off:>9} ({off / len(rows):>4.0%})  {tops}"
        )


def write_csv(path: Path, rows: list[dict], fallback_header: list[str]) -> None:
    with path.open("w", newline="") as file:
        writer = csv.DictWriter(
            file, fieldnames=list(rows[0]) if rows else fallback_header
        )
        writer.writeheader()
        writer.writerows(rows)


def cycle_breaks(rows: list[dict]) -> dict[str, list[int]]:
    """Page numbers where a unit departs from the four-page record cycle.

    The unit's phase is whichever of the four rotations matches the most pages
    -- units don't all start on the same page role, and assuming they do would
    report every unit as 100% broken.

    The expected role comes from the page's own number, not its position in the
    list: ``analyze`` samples every ~25th page, so consecutive rows here are not
    consecutive pages and walking the cycle by list index compares each page
    against an arbitrary rotation.
    """
    by_unit: dict[str, list[tuple[int, str]]] = defaultdict(list)
    for row in rows:
        by_unit[row["unit"]].append((row["page_number"], row["analysis"]["page_role"]))

    breaks: dict[str, list[int]] = {}
    for unit, pages in by_unit.items():
        pages.sort()
        best = min(
            range(4),
            key=lambda phase: sum(
                role != RECORD_CYCLE[(number - 1 + phase) % 4] for number, role in pages
            ),
        )
        breaks[unit] = [
            number
            for number, role in pages
            if role != RECORD_CYCLE[(number - 1 + best) % 4]
        ]
    return breaks


def write_reports(
    clusters: list[Cluster],
    failed: list[dict],
    breaks: dict[str, list[int]],
    out_dir: Path,
    total_pages: int,
) -> list[dict]:
    out_dir.mkdir(parents=True, exist_ok=True)

    with (out_dir / "structures.csv").open("w", newline="") as file:
        writer = csv.writer(file)
        writer.writerow(
            [
                "cluster_id",
                "page_role",
                "cards",
                "distinct_labels",
                "merged_from",
                "example",
            ]
        )
        for cluster in clusters:
            writer.writerow(
                [
                    cluster.cluster_id,
                    cluster.role,
                    cluster.size,
                    len(cluster.labels),
                    " ".join(cluster.merged),
                    cluster.cards[0]["card_id"],
                ]
            )

    # Canonical structure = the biggest cluster of each role. Fields present on
    # ~every card in it are core; the rest are where that role actually varies.
    dominant: dict[str, Cluster] = {}
    for cluster in clusters:
        dominant.setdefault(cluster.role, cluster)

    lines = ["# Canonical structures\n"]
    for role, cluster in dominant.items():
        lines.append(
            f"\n## {role} — cluster {cluster.cluster_id}, {cluster.size} cards\n"
        )
        lines.append("| field | present on | |")
        lines.append("| --- | --- | --- |")
        for label, count in label_frequency(cluster):
            share = count / cluster.size
            lines.append(
                f"| {label} | {count}/{cluster.size} ({share:.0%}) | "
                f"{'core' if share >= 0.99 else 'varies'} |"
            )
    (out_dir / "canonical.md").write_text("\n".join(lines) + "\n")

    # An exception is a card whose *structure* departs from its role's
    # canonical one. Anomalies deliberately do not qualify: the model reports
    # punch holes and paper edges on nearly every card, so keying exceptions
    # off them makes the report as long as the corpus and just as useless. They
    # get their own file, ranked by rarity, which is where a torn or overlaid
    # page that otherwise clusters normally shows up.
    exceptions: list[dict] = []
    for cluster in clusters:
        canonical = dominant[cluster.role]
        if cluster.cluster_id == canonical.cluster_id:
            continue
        for card in cluster.cards:
            labels = {
                normalise_label(f["label"])
                for f in card["analysis"]["fields"]
                if normalise_label(f["label"])
            }
            exceptions.append(
                {
                    "card_id": card["card_id"],
                    "unit": card["unit"],
                    "pdf": card["pdf"],
                    "page_number": card["page_number"],
                    "page_role": cluster.role,
                    "role_confidence": card["analysis"].get("page_role_confidence", ""),
                    "cluster_id": cluster.cluster_id,
                    "cluster_size": cluster.size,
                    "missing_vs_canonical": "; ".join(
                        sorted(canonical.labels - labels)
                    ),
                    "extra_vs_canonical": "; ".join(sorted(labels - canonical.labels)),
                    "anomalies": "; ".join(
                        str(a) for a in (card["analysis"].get("anomalies") or [])
                    ),
                    "corrections": card["analysis"].get("corrections_present", ""),
                    "unreadable": card["analysis"].get("unreadable_regions", ""),
                }
            )

    write_csv(out_dir / "exceptions.csv", exceptions, ["card_id"])
    anomalies = rank_anomalies(clusters)
    write_csv(out_dir / "anomalies.csv", anomalies, ["anomaly"])

    with (out_dir / "cycle_breaks.csv").open("w", newline="") as file:
        writer = csv.writer(file)
        writer.writerow(["unit", "pages_off_cycle", "page_numbers"])
        for unit, pages in sorted(breaks.items()):
            writer.writerow([unit, len(pages), " ".join(str(p) for p in pages[:200])])

    analysed = sum(c.size for c in clusters)
    retries = sum(
        card.get("attempts", 1) - 1 for cluster in clusters for card in cluster.cards
    )
    seconds = sum(
        card.get("elapsed_s", 0.0) for cluster in clusters for card in cluster.cards
    )
    report = [
        "# Processing report\n",
        f"- Pages with a result: {total_pages}",
        f"- Analysed successfully: {analysed}",
        f"- Failed: {len(failed)}",
        f"- Retries spent: {retries}",
        (
            f"- Model time: {seconds / 3600:.1f} h across all workers "
            f"({seconds / analysed:.0f}s per page)"
        ),
        f"- Structures found: {len(clusters)} across {len(dominant)} page roles",
        f"- Exceptions (off-canonical structure): {len(exceptions)}",
        f"- Distinct anomalies reported: {len(anomalies)}",
        (
            "- Units with pages off the four-page cycle: "
            f"{sum(1 for pages in breaks.values() if pages)}/{len(breaks)}"
        ),
        "",
        "## Failures\n",
    ]
    for row in failed[:100]:
        report.append(f"- {row['card_id']}: {row.get('error')}")
    if len(failed) > 100:
        report.append(f"- ... and {len(failed) - 100} more (see pages.jsonl)")
    (out_dir / "processing.md").write_text("\n".join(report) + "\n")
    return exceptions


def export_exception_images(exceptions: list[dict], out_dir: Path) -> int:
    """Pull just the exception pages' scans out of the PDFs, so a human review
    of the report doesn't mean hunting page 731 of a 1,046-page file."""
    images_dir = out_dir / "exception_images"
    images_dir.mkdir(parents=True, exist_ok=True)
    written = 0
    for pdf_path, group in _grouped_by_pdf(exceptions):
        reader = open_unit(Path(pdf_path))
        for row in group:
            try:
                image = page_image(reader, row["page_number"])
            except Exception as error:  # noqa: BLE001 -- already an exception page
                print(f"could not export {row['card_id']}: {error}")
                continue
            suffix = ".jpg" if image.mime == "image/jpeg" else ".jp2"
            (images_dir / f"{row['card_id']}{suffix}").write_bytes(image.data)
            written += 1
    return written


def card_labels(card: dict) -> set[str]:
    return {
        normalise_label(f["label"])
        for f in card["analysis"]["fields"]
        if normalise_label(f["label"])
    }


def export_reference_cards(clusters: list[Cluster], out_dir: Path) -> tuple[int, Path]:
    """One example scan per front-card structure, as PNG, plus an index.

    The rest of the report answers "what structures exist" in labels. This
    answers it in pictures, because you cannot tell from a label list whether
    two clusters are two forms or one form scanned badly twice -- and on this
    data most of them are the latter.

    Fronts only. A reverse carries no printed labels, so every reverse clusters
    on role alone and an example of one would show nothing about structure.
    (Note that is not the same as a reverse being empty: 57% of them carry
    handwriting, which is a transcription question, not a structural one.)

    Sends nothing -- the scans come out of the PDFs already on disk.
    """
    # Filter by page parity, not by the model's role label. The label is the
    # unreliable signal: a blank reverse whose printed front shows through the
    # paper gets read as a front, mirrored, and lands in its own cluster. Four
    # such bleed-throughs were shipped as "front structures" before this, and
    # every one of them sat on a reverse page.
    #
    # The phase is per unit, not global: five units (216412, 216415, 216420,
    # 216423, 216447) number their fronts even, so a global "fronts are odd"
    # rule would throw away their real cards. Take the phase from the pages the
    # model called a front -- wrong on individual pages, right in bulk.
    phase: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for cluster in clusters:
        if cluster.role in FRONT_ROLES:
            for card in cluster.cards:
                phase[card["unit"]][card["page_number"] % 2] += 1
    front_parity = {u: (1 if c[1] >= c[0] else 0) for u, c in phase.items()}

    def on_front_page(card: dict) -> bool:
        return card["page_number"] % 2 == front_parity.get(card["unit"], 1)

    fronts = []
    for cluster in clusters:
        if cluster.role not in FRONT_ROLES:
            continue
        if not any(on_front_page(card) for card in cluster.cards):
            continue  # every page in it is a reverse: bleed-through, not a form
        fronts.append(cluster)
    fronts.sort(key=lambda c: (FRONT_ROLES.index(c.role), -c.size))
    if not fronts:
        return 0, out_dir / "front_structures.md"

    # Canonical = the biggest cluster of each role, matching canonical.md.
    canonical: dict[str, Cluster] = {}
    for cluster in fronts:
        canonical.setdefault(cluster.role, cluster)

    images_dir = out_dir / "reference_cards"
    images_dir.mkdir(parents=True, exist_ok=True)
    # Clear first. The set of front clusters shrinks as well as grows -- adding
    # the parity filter took it from 11 to 6 -- and a stale PNG from a previous
    # run is worse than no PNG, because it looks like a current finding.
    for old_png in images_dir.glob("*.png"):
        old_png.unlink()

    # The card that best matches its own cluster's label set, not cards[0]: a
    # cluster's first card can be the rotated or bled-through scan that dragged
    # it off canonical in the first place, which is the worst thing to hand
    # someone as "this is what this structure looks like".
    # Overlap first, then label count as the tie-break. Overlap alone is not
    # enough: a merged cluster keeps the label set of whichever side absorbed
    # the other, so if that side was the sparse bad scan every card ties at its
    # handful of labels and the bad scan wins by being first.
    picks = [
        (
            c,
            max(
                [card for card in c.cards if on_front_page(card)] or c.cards,
                key=lambda card: (
                    len(card_labels(card) & c.labels),
                    len(card_labels(card)),
                ),
            ),
        )
        for c in fronts
    ]

    by_pdf: dict[str, list[tuple[Cluster, dict]]] = defaultdict(list)
    for cluster, card in picks:
        by_pdf[card["pdf"]].append((cluster, card))

    names: dict[str, str] = {}
    for pdf_path, group in sorted(by_pdf.items()):
        try:
            reader = open_unit(Path(pdf_path))
        except Exception as error:  # noqa: BLE001 -- 216436 is corrupt by nature
            # One unreadable unit must not cost every other unit's reference
            # card. The index still lists the cluster, without a link.
            print(f"could not open {pdf_path}: {error}")
            continue
        for cluster, card in group:
            name = f"{cluster.role}_{cluster.cluster_id}_{card['card_id']}.png"
            try:
                image = page_image(reader, card["page_number"])
                Image.open(io.BytesIO(image.data)).save(images_dir / name)
            except Exception as error:  # noqa: BLE001 -- one bad scan is not fatal
                print(f"could not export {card['card_id']}: {error}")
                continue
            names[cluster.cluster_id] = name

    lines = [
        "# Front-card structures",
        "",
        f"Every cluster with role {' or '.join(FRONT_ROLES)}, one example scan each,",
        "numeric (`coding-front`) first. Reverses are excluded by design.",
        "",
        "**Cluster count is not form count.** A cluster is a distinct *label set*,",
        "so a page the model read through a rotation, a bleed-through or a white",
        "block lands in its own cluster while being the same printed form. The",
        "`shared with canonical` column is what separates the two: a real variant",
        "shares few labels with the canonical set, a bad scan of the canonical form",
        "shares some but is missing the rest. Open the PNG to settle it.",
        "",
        "| structure | role | cards | labels | shared with canonical | example scan |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for cluster, card in picks:
        base = canonical[cluster.role]
        shared = len(cluster.labels & base.labels)
        share = f"{shared}/{len(base.labels)}"
        if cluster.cluster_id == base.cluster_id:
            share = "canonical"
        name = names.get(cluster.cluster_id)
        link = (
            f"[{card['card_id']}](reference_cards/{name})" if name else "export failed"
        )
        lines.append(
            f"| `{cluster.cluster_id}` | {cluster.role} | {cluster.size} | "
            f"{len(cluster.labels)} | {share} | {link} |"
        )
    lines.append("")

    index = out_dir / "front_structures.md"
    index.write_text("\n".join(lines) + "\n")
    return len(names), index


def _grouped_by_pdf(exceptions: list[dict]):
    by_pdf: dict[str, list[dict]] = defaultdict(list)
    for row in exceptions:
        by_pdf[row["pdf"]].append(row)
    return sorted(by_pdf.items())


def build_reports(
    *,
    results: Path,
    out: Path,
    merge_threshold: float,
    export_images: bool,
    sweep: bool = False,
    reference_cards: bool = False,
) -> None:
    if not results.exists():
        raise SystemExit(f"No results at {results} -- run the analyze step first")

    rows, failed = load_rows(results)
    if not rows:
        raise SystemExit(f"No successful rows in {results} ({len(failed)} failed)")

    if sweep:
        sweep_thresholds(rows)
        return

    clusters = cluster_rows(rows, merge_threshold)
    exceptions = write_reports(
        clusters, failed, cycle_breaks(rows), out, len(rows) + len(failed)
    )

    print(f"{len(rows)} analysed, {len(failed)} failed, {len(clusters)} structures\n")
    for cluster in clusters[:15]:
        print(f"  {cluster.cluster_id}  {cluster.role:<14} {cluster.size:>6} cards")
    if len(clusters) > 15:
        print(f"  ... and {len(clusters) - 15} more")
    print(f"\n{len(exceptions)} exceptions -> {out}/exceptions.csv")
    print(f"anomalies ranked rarest-first -> {out}/anomalies.csv")
    if export_images:
        print(f"{export_exception_images(exceptions, out)} scans exported")
    if reference_cards:
        written, index = export_reference_cards(clusters, out)
        print(f"{written} front-card reference PNGs -> {out}/reference_cards/")
        print(f"front-structure index -> {index}")

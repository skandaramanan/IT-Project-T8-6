"""Pass 3: show the model representatives of each structure side by side.

Pass 1 sees one page at a time and so cannot tell a real archival variant from
its own transcription wobble. This pass can: it puts a few real scans from each
cluster in one context, with the cluster sizes, and asks which differences are
genuine. That is the only question in this pipeline that needs a model to see
several cards at once, which is why it is the only place a multi-image call is
worth its cost.

Representatives are spread across each cluster rather than taken from the
front, so a cluster whose first dozen cards all come from one unit doesn't get
characterised by that unit alone.

Run via the CLI: ``uv run main.py synthesize`` (see structure/cli.py).
"""

from __future__ import annotations

import os
from pathlib import Path

from structure.analyze import (
    Client,
    RateGate,
    image_part,
)
from structure.inventory import open_unit, page_image
from structure.report import Cluster, cluster_rows, label_frequency, load_rows

PROMPT_HEADER = """You are looking at representative scans from a 1941-43 Australian social survey archive. An earlier pass described each page on its own and grouped the descriptions into the clusters below. Those clusters may over-split: two clusters can be the same printed form, separated only by how the earlier pass read a label.

Cluster summary:

"""

PROMPT_FOOTER = """

The images follow, labelled with their cluster and card id.

Write a short markdown report answering, with evidence from the images:

1. What is the canonical structure of each page role? List its fields in order.
2. Which fields are on every card of that role, and which genuinely vary?
3. For each cluster that is NOT the largest of its role: is it a real structural variant, or the same form transcribed differently? Say which, and what specifically shows it.
4. Where variants are real, what distinguishes them -- a different printing of the form, a different survey round, a different municipality's practice, something else?
5. Which cards or clusters a human should look at directly, and why.

Cite card ids. Do not speculate beyond what the images show; say "cannot tell from these scans" where that is the honest answer."""


def representatives(cluster: Cluster, count: int) -> list[dict]:
    """Evenly spaced across the cluster, so the sample isn't all one unit."""
    if cluster.size <= count:
        return list(cluster.cards)
    step = cluster.size / count
    return [cluster.cards[int(index * step)] for index in range(count)]


def cluster_summary(clusters: list[Cluster]) -> str:
    lines = []
    for cluster in clusters:
        top = ", ".join(label for label, _ in label_frequency(cluster)[:12])
        lines.append(
            f"- cluster {cluster.cluster_id}: role {cluster.role}, {cluster.size} cards, "
            f"{len(cluster.labels)} distinct field labels. First labels: {top}"
        )
    return "\n".join(lines)


def build_content(clusters: list[Cluster], per_cluster: int) -> tuple[list[dict], int]:
    content: list[dict] = [
        {
            "type": "text",
            "text": PROMPT_HEADER + cluster_summary(clusters) + PROMPT_FOOTER,
        }
    ]
    readers: dict[str, object] = {}
    included = 0
    for cluster in clusters:
        for card in representatives(cluster, per_cluster):
            reader = readers.get(card["pdf"])
            if reader is None:
                reader = readers[card["pdf"]] = open_unit(Path(card["pdf"]))
            try:
                image = page_image(reader, card["page_number"])
            except Exception as error:  # noqa: BLE001 -- skip, don't sink the synthesis
                print(f"skipping {card['card_id']}: {error}")
                continue
            content.append(
                {
                    "type": "text",
                    "text": f"cluster {cluster.cluster_id} ({cluster.role}), "
                    f"card {card['card_id']}, {card['pdf']} page {card['page_number']}:",
                }
            )
            content.append(image_part(image.data, image.mime))
            included += 1
    return content, included


def synthesise(
    *,
    results: Path,
    out: Path,
    model: str,
    merge_threshold: float,
    clusters: int,
    per_cluster: int,
    max_tokens: int,
    reasoning_effort: str,
) -> None:
    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        raise SystemExit("OPENROUTER_API_KEY is not set (see .env.example)")

    rows, _ = load_rows(results)
    chosen = cluster_rows(rows, merge_threshold)[:clusters]
    content, included = build_content(chosen, per_cluster)
    print(f"Synthesising over {included} scans from {len(chosen)} clusters...")

    client = Client(
        api_key=api_key,
        model=model,
        gate=RateGate(20.0),
        max_tokens=max_tokens,
        reasoning_effort=reasoning_effort,
    )
    text, attempts = client.chat(content, json_mode=False)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text)
    print(f"Written to {out} (attempt {attempts})")

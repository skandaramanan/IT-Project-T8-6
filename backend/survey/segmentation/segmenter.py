"""Splits a combined survey scan into its front/reverse/numeric_coding
card inputs (FR-19)."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

import numpy as np
from PIL import Image


class CardType(StrEnum):
    FRONT = "front"
    REVERSE = "reverse"
    NUMERIC_CODING = "numeric_coding"


_DARK_THRESHOLD = 170  # grayscale cutoff for "ink" vs. paper
_RULED_LINE_FRACTION = 0.6  # ink fraction for a row/col to count as ruled
_MAX_RULED_RUN_LENGTH = 4  # thin printed rule vs. a solid dark region
_MIN_RULED_LINE_COUNT = 3  # thin runs needed to call a page "front"
_BLANK_INK_MAX = 0.002  # below this, page is blank
_REVERSE_CODING_SPLIT = 0.035  # reverse vs. numeric_coding, by ink fraction
_REVERSE_OVERRIDE_MAX = 0.10  # ceiling for trusting position over content -- FR-21
_ANALYSIS_MAX_DIM = 900  # downscale target for feature extraction
_EDGE_TRIM_FRACTION = 0.03  # trims scan-bed borders before analysis


@dataclass(frozen=True)
class PageFeatures:
    ink_fraction: float
    ruled_rows: int  # thin dark-row run count
    ruled_cols: int  # thin dark-col run count


def _count_thin_runs(is_dark: np.ndarray) -> int:
    """Count of runs no longer than _MAX_RULED_RUN_LENGTH."""
    count = 0
    run_length = 0
    for value in is_dark:
        if value:
            run_length += 1
        else:
            if 0 < run_length <= _MAX_RULED_RUN_LENGTH:
                count += 1
            run_length = 0
    if 0 < run_length <= _MAX_RULED_RUN_LENGTH:
        count += 1
    return count


def _page_features(image_path: Path) -> PageFeatures:
    img = Image.open(image_path).convert("L")
    width, height = img.size
    scale = _ANALYSIS_MAX_DIM / max(width, height)
    if scale < 1:
        img = img.resize((max(1, round(width * scale)), max(1, round(height * scale))))
    width, height = img.size

    dark = np.asarray(img) < _DARK_THRESHOLD  # (height, width) bool
    trim_x = round(width * _EDGE_TRIM_FRACTION)
    trim_y = round(height * _EDGE_TRIM_FRACTION)
    dark = dark[trim_y : height - trim_y, trim_x : width - trim_x]
    ruled_rows = _count_thin_runs(dark.mean(axis=1) > _RULED_LINE_FRACTION)
    ruled_cols = _count_thin_runs(dark.mean(axis=0) > _RULED_LINE_FRACTION)
    return PageFeatures(
        ink_fraction=float(dark.mean()),
        ruled_rows=ruled_rows,
        ruled_cols=ruled_cols,
    )


def _is_front(features: PageFeatures) -> bool:
    """Summed across axes -- a real front cleared this only combined (2+1),
    not on either axis alone."""
    return (features.ruled_rows + features.ruled_cols) >= _MIN_RULED_LINE_COUNT


def _is_blank(features: PageFeatures) -> bool:
    return features.ink_fraction < _BLANK_INK_MAX


def _classify_by_ink(features: PageFeatures) -> CardType:
    """Content-only reverse vs. numeric_coding call."""
    return (
        CardType.REVERSE
        if features.ink_fraction < _REVERSE_CODING_SPLIT
        else CardType.NUMERIC_CODING
    )


def classify_page(image_path: Path) -> CardType | None:
    """Page's role, or None if blank. Prefer segment_scan() when order is known."""
    features = _page_features(image_path)
    if _is_front(features):
        return CardType.FRONT
    if _is_blank(features):
        return None
    return _classify_by_ink(features)


@dataclass(frozen=True)
class SegmentedCard:
    card_type: CardType
    image_path: Path
    source_scan: Path  # for traceability
    page_index: int  # 0-based position within the scan


def _resolve_page_roles(pages: list[Path]) -> list[CardType | None]:
    """Per-page role, using position to break the reverse/numeric_coding tie."""
    features = [_page_features(p) for p in pages]
    roles: list[CardType | None] = [None] * len(pages)
    run: list[int] = []

    def flush_run() -> None:
        if not run:
            return
        first_ink = features[run[0]].ink_fraction
        if len(run) == 1 or first_ink >= _REVERSE_OVERRIDE_MAX:
            # No ordering info, or first page too ink-heavy to trust as
            # reverse -- fall back to content alone.
            for idx in run:
                roles[idx] = _classify_by_ink(features[idx])
        else:
            roles[run[0]] = CardType.REVERSE
            roles[run[1]] = CardType.NUMERIC_CODING
            # A third-plus page (e.g. an FR-21 stray doc) stays unclassified
            # rather than clobbering the slot above.
        run.clear()

    for i, f in enumerate(features):
        if _is_front(f):
            flush_run()
            roles[i] = CardType.FRONT
        elif _is_blank(f):
            flush_run()  # roles[i] left as None -- blank isn't a card type
        else:
            run.append(i)
    flush_run()
    return roles


def segment_pages(pages: list[Path], source_scan: Path) -> list[SegmentedCard]:
    """Every card in a multi-record scan, in scan order; ``pages`` must be in
    scan order. Blank and unrecognised pages are left out."""
    return [
        SegmentedCard(
            card_type=card_type,
            image_path=page,
            source_scan=source_scan,
            page_index=index,
        )
        for index, (page, card_type) in enumerate(
            zip(pages, _resolve_page_roles(pages))
        )
        if card_type is not None
    ]


def segment_scan(
    pages: list[Path], source_scan: Path
) -> dict[CardType, SegmentedCard | None]:
    """Card inputs for one scan; ``pages`` must be in scan order."""
    result: dict[CardType, SegmentedCard | None] = {
        CardType.FRONT: None,
        CardType.REVERSE: None,
        CardType.NUMERIC_CODING: None,
    }
    for card in segment_pages(pages, source_scan):
        result[card.card_type] = card
    return result

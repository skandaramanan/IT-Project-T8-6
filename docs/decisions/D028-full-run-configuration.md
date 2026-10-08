# D028 — Full-run configuration: Flash-Lite, unbanded, no struck detection

**Status:** Accepted
**Date:** 2026-10-08
**Decided by:** Skanda Ramanan (IT-123 assignee)
**Linear issue:** IT-123

## Context

IT-123 runs `survey extract` over all 45 folders. Each card's reading is
cached under a name built from the model and the prompt switches, so the
switches set before the first request are the ones the dataset carries:
changing one later means reading every card again, about 5 to 7 days of free
quota. Three of them were open, and the documents disagreed:

- **Model.** D012 says only "Gemini". D019 notes nothing formally chose
  Flash-Lite over Flash.
- **Confidence band** (`GEMINI_CONFIDENCE_BAND`). IT-123 asked for the band.
  D022 assumes it is off. D019's fallback, if the Qwen arm never runs, is
  Flash-Lite plus its band.
- **Struck detection** (`GEMINI_STRUCK_DETECTION`, FR-06). Built under IT-91
  but never run against a real image.

## Decision

The full run uses `.env` with only the key set. Everything else stays blank:

| Setting | Value | Why |
| -- | -- | -- |
| `GEMINI_MODEL` | blank (`gemini-3.5-flash-lite`) | Its free cap, 500 requests/day/key against Flash's 20, is what makes a full run possible. D016's constants are calibrated on it. |
| `GEMINI_MEDIA_RESOLUTION` | blank | D016's runs don't record one, so its constants are only known to hold at the default. |
| `GEMINI_CONFIDENCE_BAND` | blank (off) | See below. |
| `GEMINI_STRUCK_DETECTION` | blank (off) | See below. |

Survey fronts are read as well (IT-117), at one more request each.

### Unbanded

The band costs 2.5 points of coded-field accuracy: 91.3% unbanded against
88.8% banded on the 30-card benchmark (D016 §5). With the Qwen arm, the two
choices ship about the same share of wrong values unflagged. Unbanded, both
arms catch 76.6% of Flash-Lite's errors, leaving 2.15% of fields wrong and
unflagged (D019). Banded, they catch 83% of a higher error rate (D019), about
1.9%. So the band buys little, and it complicates D022's rule, which would need
D016's `agree`/`low` case fixed before review (D022, "Assumes banding is off").

### No struck detection

Run live on 2026-10-08 against the IT-93 crossed-out fixtures (7 cards,
unbanded, default resolution), the struck prompt flagged **0 of 28** labelled
strikes, with no false positives on the 6 unmarked controls. The response was
well formed: every field carried `"struck": false`. Two of the cards rerun at
`GEMINI_MEDIA_RESOLUTION=high` still flagged nothing. Turning it on would
change the prompt the whole corpus is read with and buy no signal.

## Alternatives

- **Banded.** Keeps a confidence signal if the Qwen arm falls through (D019's
  fallback, 38.5% of errors caught). Rejected for the accuracy cost above, and
  because the band would need D022 and D016 revisited before review.
- **Struck detection on.** Rejected: it finds nothing on Flash-Lite.
- **`gemini-3.5-flash`.** Fewer unflagged errors (D019), but 20 requests/day/key
  makes a full run take months.

## Consequences

- **If the Qwen arm (IT-124) falls through, there is no confidence signal.**
  Every field Gemini returned scores the same 0.91, so everything routes to
  review (D022), and card confidence (D018) only tells cards apart by the
  fields Gemini left out. The mitigation is IT-124's 30-card check, done early
  enough to act on.
- **FR-06 (Must) is not in this dataset.** No field carries `negated`, and a
  struck option is read as if it were unmarked. IT-91's detection is not
  delivered; resolution (IT-92, D023) is built but has nothing to act on. One
  route is a reviewer marking a field struck in the review tool.
- Survey-front fields have no D016 calibration, so their confidence is null
  and they route to review (D022).
- With four keys, about 2,000 requests a day. The run is about 13,000
  requests: ~6,500 coding cards, and about as many fronts (the 216429 smoke run
  read 30 of each). So about 7 days, or 5 to 6 once a fifth key joins.

## Revisit if

- The Qwen arm falls through. Then reading the corpus again banded is the
  fallback D019 names, at a second full run.
- A model or prompt is found that detects strikes on the IT-93 fixtures.
- Paid capacity is approved (NFR-10). Flash becomes practical.

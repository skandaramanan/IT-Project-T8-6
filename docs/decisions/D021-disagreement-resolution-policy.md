# D021 — Dual-extractor disagreement resolution

**Status:** Accepted
**Date:** 2026-09-22
**Linear issue:** IT-86

## Decision

Gemini Flash-Lite is the primary extractor. For every field on a card that
Gemini returned, use Gemini's normalised value as the resolved value. A blank
is a value returned by the primary extractor; it does not cause Qwen's
non-blank value to replace it. Qwen supplies the resolved value only when the
Gemini extraction arm did not return a usable result for the entire card.

| Paired outcome | Resolved value | Marker |
| --- | --- | --- |
| `agree` | Gemini's normalised value | `source_agreement: agree` |
| `disagree` | Gemini's normalised value | `source_agreement: disagree` |
| `one_blank` | Gemini's normalised value, including blank | `source_agreement: one_blank` |
| `both_blank` | Gemini's blank value | `source_agreement: both_blank` |
| `no_second_opinion` | The surviving arm's normalised value | `source_agreement: no_second_opinion` |

`source_agreement` records whether a field was chosen by agreement or a
primary-arm rule. It is evidence for downstream review handling; this decision
does not define a review queue, threshold, or interface.

## Evidence

D019's 30-card benchmark (1,860 fields) measured Gemini Flash-Lite as correct
for 75.1% of non-blank disagreements, compared with 13.8% for Qwen. The
one-blank confidence constant, 0.74, was measured for Gemini's primary reading
and includes cases where Gemini correctly returned blank. Replacing a Gemini
blank with Qwen's populated value would therefore apply a measured confidence
to a different selected reading.

The policy does not claim that a blank is evidence the source field is empty.
The paired raw values remain available for inspection. Classification of a
source condition and downstream review routing are owned by their respective
work, not by this resolver.

## Implementation

`spike.confidence.resolve_primary_value` is the single implementation of this
rule. `score_fields` uses it before assigning the confidence score, and the
IT-86 regression tests cover every paired outcome plus the whole-arm failure
case.

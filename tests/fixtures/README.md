# Fixtures

A handful of representative cards, committed so tests have something real to run
against without reaching for the archive.

Keep this small — a few files, not a sample of the corpus. Anything large lives
in shared storage and stays out of git (see `data/`, which is gitignored).

Not to be confused with:

- the **benchmark set** — the larger, hand-checked set the extraction spike
  measures accuracy against;
- the client's **1980s transcription data**, used for end-to-end validation.

## What's here

Five consecutive survey records, 20 images, 7.2 MB. Each record is four pages,
and that four-page cycle is the repeating unit the pipeline has to recognise:

| File | What it is |
| --- | --- |
| `rNN-survey-front.jpg` | The handwritten household survey — address, occupants, earnings, dwelling details |
| `rNN-survey-back.jpg` | Interviewer's free-text notes |
| `rNN-coding-front.jpg` | The **numeric coding card** — typed field labels, handwritten numeric values. The primary extraction target |
| `rNN-coding-back.jpg` | Blank. Carries nothing but show-through from the front |

The blank backs are kept deliberately. Every record here has one, so blank pages
are structural rather than rare, and page-sorting code has to handle them. A
fixture set with none would let blank-detection bugs through.

`r01` and `r03` both carry red pencil corrections struck through earlier values —
the crossed-out case the client flagged as implicit negation. Worth pointing
tests at when that handling lands.

## Reverse-side notes (FR-05)

`reverse_notes/ground_truth.json` is the note text each survey back should
yield, checked by `tests/test_reverse_note_fixtures.py`. It covers all five
`rNN-survey-back.jpg` files above, plus two later backs copied into
`reverse_notes/` for the cases pages 1 to 20 lack: a blank back and an overflow
dwelling.

| PDF page | Image | Case | Record |
| --- | --- | --- | --- |
| 2 | `r01-survey-back.jpg` | dense | 27-0006-01 |
| 6 | `r02-survey-back.jpg` | hard | 27-0007-01 |
| 10 | `r03-survey-back.jpg` | hard | 27-0012-01 |
| 14 | `r04-survey-back.jpg` | dense | 27-0014-01 |
| 18 | `r05-survey-back.jpg` | sparse | 27-0023-01 |
| 66 | `reverse_notes/p066-survey-back.jpg` | dense, overflow | 27-0046-01 |
| 68 | `reverse_notes/p068-survey-back.jpg` | blank, overflow | 27-0046-01 |

Pages 65 to 69 are one dwelling at 89 Elphin St with two fronts: the main one
(65, notes on 66) and an overflow sheet for two boarders (67, blank back 68),
then a single coding card (69). The pair tests that both backs land on the same
record, one with text and one with an explicit empty.

Every expected note follows the verbatim rules in the test's docstring and was
checked by a person against the scan.

## Provenance

All of it comes from `1260908_1973-0002-00049.pdf`, from the shared Drive
folder (see the README).

- `reverse_notes/p066-survey-back.jpg` and `p068-survey-back.jpg` are pages 66
  and 68, named by their page. Every survey back in pages 1 to 20 carries notes,
  so the set had no blank back to test the explicit empty against (IT-90 AC4).
  Page 68 is a blank back from the same PDF, and page 66 comes with it because
  both belong to one overflow dwelling: two fronts, each with its own back, and
  one coding card (page 69).

## Why JPEG and not PNG

Each PDF page is a single embedded JPEG at roughly 3800×2400. These files are
those JPEGs copied out byte-for-byte — no re-encode, no resampling, no DPI
choice. They are exactly what the archive holds.

Converting to PNG would losslessly re-wrap pixels that are already lossy: no
fidelity gained, and scans this size run 5–15 MB each as PNG, which would put
roughly 150 MB in git forever instead of 7.2 MB.

If you ever need to regenerate them:

```python
from pypdf import PdfReader

r = PdfReader("1260908_1973-0002-00049.pdf")
for i, page in enumerate(r.pages, 1):
    for _, ref in page["/Resources"]["/XObject"].get_object().items():
        obj = ref.get_object()
        if obj.get("/Subtype") == "/Image":
            open(f"p{i:02d}.jpg", "wb").write(obj._data)  # raw stream, no re-encode
```

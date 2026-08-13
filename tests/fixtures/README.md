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

The blank backs are kept deliberately. Roughly a quarter of the corpus is blank
pages, so page-sorting code has to handle them, and a fixture set without any
would let blank-detection bugs through.

`r01` and `r03` both carry red pencil corrections struck through earlier values —
the crossed-out case the client flagged as implicit negation. Worth pointing
tests at when that handling lands.

## Provenance

Pages 1–20 of `1973-0002-00049-1-25-1-20.pdf`, from the shared Drive folder
(see the README). File order maps straight through: page 1 is
`r01-survey-front.jpg`, page 20 is `r05-coding-back.jpg`.

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
r = PdfReader("1973-0002-00049-1-25-1-20.pdf")
for i, page in enumerate(r.pages, 1):
    for _, ref in page["/Resources"]["/XObject"].get_object().items():
        obj = ref.get_object()
        if obj.get("/Subtype") == "/Image":
            open(f"p{i:02d}.jpg", "wb").write(obj._data)  # raw stream, no re-encode
```

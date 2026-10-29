# Survey Card Extractor: user manual

Turns a folder of scanned survey PDFs (one *region*) into one results file.

| Section | Jump to |
| --- | --- |
| **[Setup](#setup)**<br>Once per computer | [Install](#1-install-git-and-uv) · [Code](#2-get-the-code) · [Scans](#3-get-the-scans) · [Gemini key](#4-get-a-gemini-api-key) · [Settings](#5-fill-in-the-settings-file) |
| **[Running](#running-an-extraction)** | [Start](#start-a-run) · [Summary](#read-the-summary) · [Options](#options) |
| **[Stopping and resuming](#stopping-and-resuming)** | Daily limit, rerunning, `--fresh` |
| **[Using the results](#using-the-results)** | Output, check, review list |
| **[Second reading](#second-reading-optional)** | Optional |
| **[Troubleshooting](#troubleshooting)** | |
| **[Practice run](#practice-run)** | |

---

## Setup

| What | Example (Windows) |
| --- | --- |
| Code folder (results go in its `results` folder) | `C:\Survey Extract\survey-extract` |
| Scans folder, one subfolder per region | `C:\Survey Scans` |
| Settings file | `.env` in the code folder |

Keep the two folders separate.

### 1. Install Git and uv

Install Git from [git-scm.com](https://git-scm.com/downloads). Then run:

```bat
winget install --id=astral-sh.uv
```

On a Mac, use `brew install uv`. Open a new terminal afterwards.

### 2. Get the code

```bat
git clone https://github.com/skandaramanan/IT-Project-T8-6.git "C:\Survey Extract\survey-extract"
cd /d "C:\Survey Extract\survey-extract"
uv sync --locked
```

### 3. Get the scans

Download the region folders from the shared Google Drive into your scans folder.
If Drive shows a request-access screen, switch to your student Google account.
Scans are never committed to Git.

### 4. Get a Gemini API key

1. Go to [aistudio.google.com/apikey](https://aistudio.google.com/apikey).
2. Choose **Create API key** and copy it.
3. Don't add billing. The project uses the free tier.

**Privacy:** on the free tier, Google may use what you send and human reviewers may
read it. See the ethics report, and check the team has agreed before you send real scans.

### 5. Fill in the settings file

Copy `.env.example` to `.env` and set:

```dotenv
GEMINI_API_KEY=paste-your-key-here
```

Leave the other lines blank. Never commit `.env`. If the key leaks, delete it at
the link above and make a new one.

**Limit:** about 500 cards per key per day. The full set is about 6,500 cards, and
each survey front costs one more request, so a full run takes days.

---

## Running an extraction

### Start a run

```bat
cd /d "C:\Survey Extract\survey-extract"
uv run survey extract "C:\Survey Scans\216429"
```

The region is named after the folder. Use one folder under one name only. Leave the
window open until it finishes.

The tool splits each PDF into pages, has Gemini read each card, groups the cards
into dwellings, scores confidence, and writes `results\216429.jsonl`.

### Read the summary

The last line counts: records written, pages skipped, cards unreadable, cards
unplaced, cards failed, PDFs failed, records invalid. If any card, PDF or record
failed, the run exits with an error. Fix the cause and rerun.

### Options

| Option | Does |
| --- | --- |
| `--region name` | Sets the region name (lowercase letters, digits, `-`, `_`) |
| `--notes` | Also reads interview notes on survey backs (one more request each) |
| `--fresh` | Reads every card again |
| `--model qwen2.5-vl-server` | Uses your own Qwen server |

---

## Stopping and resuming

- **Daily limit:** after 3 cards fail in a row the run stops and saves what it has.
  Wait a day or put another key in `.env`, then run **the same command**. Cards
  already read are replayed from `data\runs` on this computer. On another computer
  every card is read again.
- **Rerunning is safe.** No duplicates, and a reviewer's corrections are never
  overwritten. Once review starts, rerun on the copy holding the reviewed file, and
  don't extract while reviewers work.
- **`--fresh`** moves saved readings aside and rereads everything. Use it after
  changing a prompt. If it is cut short, rerun **without** `--fresh`.

---

## Using the results

`results\<region>.jsonl` has one line per dwelling. Each field has a value, a status
and a confidence from 0 to 1. A dwelling flag such as `paired_by_position` means a
judgement call. Layout: [`schema/record-envelope.schema.json`](schema/record-envelope.schema.json).

Check the results, then make the review list:

```bat
uv run survey validate-results results
uv run survey flags results > flags.jsonl
```

`flags.jsonl` lists every field a person should check. Give it to the review tool
([REVIEW-TOOL-MANUAL.md](REVIEW-TOOL-MANUAL.md)).

**Accuracy:** about 91% of coded fields were right in testing, and about 2% are
wrong without being flagged. That is why people review.

---

## Second reading (optional)

A second reading by Qwen2.5-VL on your own computer lets the tool score confidence
by agreement between two models, and the scans stay on your machine. Run an
OpenAI-compatible server such as LM Studio with a Qwen2.5-VL model loaded, then set
in `.env`:

```dotenv
QWEN_SERVER_URL=
QWEN_SERVER_MODEL=
QWEN_SERVER_WEIGHTS=
QWEN_MAX_PIXELS=2000000
```

Leave the URL blank for LM Studio's default, and the model blank if only one is
loaded. Set the weights to the file you loaded (for example `Q6_K`). Then add
`--model qwen2.5-vl-server` to the extract command. The team merges the two readings
afterwards ([merge report](docs/runs/it125-merge-report.md)).

---

## Troubleshooting

| What you see | What to do |
| --- | --- |
| `GEMINI_API_KEY is not set` | Redo step 5. |
| Run stops after 3 failures | Daily limit or outage. Wait or switch key, then rerun. |
| One card fails every run | Failed readings are saved. Delete its file in `data\runs\<region>\` (`<pdf>_pNNNN.json`) or use `--fresh`. |
| "refuses a results file holding another region's records" | One folder, one name. |
| Run stops naming a line or page, writes nothing | A damaged results file, or a reviewed record that no longer matches its scan. Fix it and rerun. |
| Pages skipped | Not a recognised card, or the PDF wouldn't open. The rest carries on. |
| Odd results on a new batch | The tool is built for coding cards C1 and C2. Other forms need new testing. |
| `uv sync --locked` fails | Ask the team. |

---

## Practice run

Copy a few PDFs into a new folder and write the results elsewhere:

```bat
set SURVEY_OUTPUT_DIR=C:\Survey Extract Practice
uv run survey extract "C:\Survey Practice Scans" --region practice
```

On a Mac, run `export SURVEY_OUTPUT_DIR=/path/to/practice` first. This spends a few
of your daily requests. Delete the folder when done.

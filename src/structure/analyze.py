"""Pass 1: ask the model what structure each page actually has, one page per job.

Every page in the archive is an independent job. A bounded worker pool pulls
jobs, posts the page scan to OpenRouter, validates the JSON that comes back,
and appends one line to a JSONL file. Nothing is held in memory across jobs and
nothing already written is ever rewritten, so a crash at page 5,000 costs the
in-flight requests and nothing else -- rerun the same command and it resumes.

What this pass deliberately does NOT ask the model:

- whether the page is a "structural variant". Variance only exists relative to
  the rest of the corpus, which a single-page call cannot see. Asking anyway
  produces a per-page opinion that reads like evidence and isn't. Clustering in
  report.py decides what is a variant, from the labels reported here.
- to match a known schema. src/extraction/field_schema.py already holds the 60
  coding-card fields; this pass exists to find where reality departs from that,
  which it can only do if it isn't told the answer first.

Rate limits, measured rather than assumed -- and the earlier measurement was
wrong. A probe of 120 pages drew no 429 and no daily wall, and this file used
to conclude from that that no cap binds. It does. On 2026-08-23 the API
returned:

    429 Rate limit exceeded: free-models-per-day-stealth
    X-RateLimit-Limit: 1000  X-RateLimit-Remaining: 0
    limit_source: openrouter_free_tier_daily

A thousand free-model requests per day, resetting at 00:00 UTC. The first
probe never reached it, which is why it saw nothing; absence of a 429 at 300
requests says nothing about the cap at 1,000.

That changes which knob matters. --workers is a latency knob and buys no extra
requests against a daily ceiling, and two things actively spend the budget for
nothing: a request that crosses the 300s client timeout is still counted, and
each stubborn page can spend up to `attempts` of it. The day this was measured,
four concurrent runs at 1,114 workers between them consumed the entire 1,000 in
their opening wave and recorded zero rows, because every request was queued
past the timeout. Hence the flock in run_analysis: one writer at a time.

Queueing binds too, independently of the cap. The provider absorbs excess
concurrency by getting slower, not by refusing: at 60 workers latency ran 26s
-> 123s and the tail crossed the 300s client timeout, giving 18.9 pages/min; at
32 workers it gave 27.5. So --rpm defaults to 0 (no gate) and --workers is the
knob for wall-clock time. A 429 holds the whole pool for its Retry-After and is
counted in the run summary, so a throttled run is distinguishable from a slow
one -- note that a daily 429 sets Retry-After to the next reset, which parks
every worker for hours rather than seconds.

Batching is the only lever against a cap that counts requests, and on
2026-08-24 it was measured and it does not work here. --batch exists and is
correct -- one request, one row per page, keyed by card id -- but the upstream
enforces a generation ceiling at roughly 175 seconds, and more than one scan
per request crosses it:

    batch 1   16-114s   22/30 pages ok
    batch 5   175-180s, uniform    0/30
    batch 10  ~178s per attempt    0/30

Uniform latency at the point of failure is the tell: this is a wall the
provider holds up, not queueing, and not our client timeout, which was set to
540s and 840s for those arms. The failure arrives as a 200 -- OpenRouter pads
the socket with whitespace while the upstream works, then closes it with either
nothing or an {"error": ...} behind the padding. Neither has a "choices" key,
which is why _post reads the envelope before indexing into it.

So the daily cap and the per-request time limit bind together, and no
combination of them fits 21,722 pages into 1,000 requests a day. What is left
is making a single page cheaper (smaller images) or not sending every page
(sample, or filter the near-blank backs) -- not more pages per request.

Run via the CLI: ``uv run main.py analyze`` (see structure/cli.py).
"""

from __future__ import annotations

import base64
import fcntl
import json
import os
import re
import sys
import threading
import time
import urllib.error
import urllib.request
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

from structure.inventory import (
    Page,
    UnreadablePdf,
    find_unit_pdfs,
    open_unit,
    page_image,
    unit_pages,
)

API_URL = "https://openrouter.ai/api/v1/chat/completions"
DEFAULT_MODEL = "stealth/ox-alpha"
DEFAULT_RESULTS = Path("results/pages.jsonl")
TIMEOUT_SECONDS = 300  # this model's p99 is minutes, not seconds

PROMPT = """This is one page from a 1941-43 Australian social survey archive, scanned as-is.

Report ONLY what is visibly on this page. Do not infer fields that are not printed on it. Do not normalise historical terminology. Do not guess at values you cannot read.

Return a JSON object with exactly these keys:

{
  "page_role": one of "coding-front", "coding-back", "survey-front", "survey-back", "blank", "other",
  "page_role_confidence": "high" | "medium" | "low",
  "printed_title": the printed heading at the top of the form, copied verbatim, or null if there is none,
  "fields": [{"label": the printed field label, copied verbatim, "type": "text" | "integer" | "date" | "checkbox" | "code" | "unknown", "filled": true or false}],
  "layout": one short phrase describing the arrangement, e.g. "two-column printed grid, handwritten codes down the right margin",
  "handwriting_present": true or false,
  "corrections_present": true or false,
  "anomalies": [short strings, one per structurally unusual thing: a missing section, an extra stamp, a torn or obscured area, two forms on one page, a rotated or upside-down scan, anything that does not fit the rest of the page],
  "unreadable_regions": true or false
}

"fields" must list every printed field label on the page, in reading order, whether or not anything is written in it. "filled" says whether a value has been written in, and nothing about what that value is. If the page is blank or carries no printed labels, return an empty list.

Copy labels exactly as printed, including abbreviations and punctuation. Do not expand, correct, or tidy them."""


def batch_prompt(card_ids: list[str]) -> str:
    """The same per-page schema, asked for N pages at once.

    The cap counts requests, not pages, so K pages per request divides the
    daily budget by K. What that buys has to be paid for in isolation: the
    per-page prompt opens "This is one page", and with several in context the
    model can carry a field or a title across them. Hence the explicit
    independence instruction, the card id printed before each image, and a
    reply keyed by card id -- a batch that drops or invents an id fails
    validation and is retried whole, rather than quietly returning K-1 pages.

    The field schema itself is spliced out of PROMPT rather than restated, so
    the two arms of a batching comparison cannot drift apart.
    """
    schema = PROMPT.split("Return a JSON object with exactly these keys:\n\n", 1)[1]
    return f"""These are {len(card_ids)} SEPARATE pages from a 1941-43 Australian social survey archive, scanned as-is. Each image is preceded by a line giving its card id.

Analyse each page independently. Do not carry a field, title, layout or anomaly from one page to another. Two pages that share a layout must still each be reported in full -- never abbreviate one by referring to another.

Return a JSON object of the form {{"pages": {{"<card id>": <analysis>, ...}}}}, with exactly one entry for each of these {len(card_ids)} ids and no others:

{chr(10).join(card_ids)}

Each <analysis> is an object with exactly these keys:

{schema}"""


REQUIRED_KEYS = {"page_role", "fields", "anomalies"}
VALID_ROLES = {
    "coding-front",
    "coding-back",
    "survey-front",
    "survey-back",
    "blank",
    "other",
}


class RateGate:
    """One shared clock for every worker: hands out send slots, and moves them
    all back together when the provider says to slow down."""

    def __init__(self, rpm: float) -> None:
        self._interval = 60.0 / rpm if rpm > 0 else 0.0
        self._lock = threading.Lock()
        self._next_slot = 0.0
        # A throttled run and a slow run look identical from the outside: both
        # are just fewer pages per minute. These make the difference legible,
        # which is the whole point of being able to raise --rpm and see what
        # happens.
        self.pauses = 0
        self.paused_seconds = 0.0

    def wait(self) -> None:
        with self._lock:
            now = time.monotonic()
            slot = max(now, self._next_slot)
            self._next_slot = slot + self._interval
        delay = slot - now
        if delay > 0:
            time.sleep(delay)

    def pause(self, seconds: float) -> None:
        with self._lock:
            self.pauses += 1
            self.paused_seconds += seconds
            self._next_slot = max(self._next_slot, time.monotonic() + seconds)


@dataclass
class Client:
    api_key: str
    model: str
    gate: RateGate
    max_tokens: int
    reasoning_effort: str
    attempts: int = 4
    timeout: float = TIMEOUT_SECONDS

    def analyse(self, image: bytes, mime: str) -> tuple[dict, int]:
        """(parsed analysis, attempts used). Raises on give-up."""
        return self.chat(
            [{"type": "text", "text": PROMPT}, image_part(image, mime)],
            json_mode=True,
            parse=lambda text: validate(parse_json(text)),
        )

    def analyse_batch(self, items: list[tuple[str, bytes, str]]) -> tuple[dict, int]:
        """({card_id: analysis}, attempts used) for (card_id, image, mime) items."""
        card_ids = [card_id for card_id, _, _ in items]
        content: list[dict] = [{"type": "text", "text": batch_prompt(card_ids)}]
        for card_id, image, mime in items:
            content.append({"type": "text", "text": f"card id: {card_id}"})
            content.append(image_part(image, mime))
        return self.chat(
            content,
            json_mode=True,
            parse=lambda text: validate_batch(parse_json(text), card_ids),
        )

    def chat(self, content: list[dict], json_mode: bool, parse=None) -> tuple:
        """(model text or parse(text), attempts used).

        Almost everything this provider does wrong, it does transiently. A 200
        whose body says "no image actually came through with your message" on a
        request that carried one; an empty 200 after ~187s of queueing; a bare
        400 "Provider returned error" on one page while 119 others take the
        same path. All of them come good on a retry, so all of them are
        retried. Only a 401/403/404 and a response we cannot even parse into a
        Python object are treated as settled.
        """
        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": content}],
            "max_tokens": self.max_tokens,
            "reasoning": {"effort": self.reasoning_effort},
        }
        if json_mode:
            # Cuts the commentary-and-fences failure mode at the source; the
            # parser still copes, because response_format is a request to the
            # provider, not a guarantee from it.
            payload["response_format"] = {"type": "json_object"}
        body = json.dumps(payload).encode("utf-8")

        last_error: Exception | None = None
        for attempt in range(1, self.attempts + 1):
            self.gate.wait()
            try:
                text = self._post(body)
                return (parse(text) if parse else text), attempt
            except RetryableError as error:
                last_error = error
                backoff = min(2**attempt, 30)
                if error.status == 429:
                    # Being over the limit is a fact about the account, not
                    # about this request: hold every worker, or the other
                    # fifteen spend the window re-earning the same 429. Applies
                    # whether or not the provider named a Retry-After.
                    self.gate.pause(error.retry_after or backoff)
                else:
                    time.sleep(backoff)  # a 5xx or a dropped socket is local
            except (ValueError, TypeError) as error:
                # A 200 with an answer we can't use -- see the docstring.
                last_error = error
                time.sleep(min(2**attempt, 30))
            except Exception as error:  # noqa: BLE001 -- a 400 stays a 400
                last_error = error
                break
        # The count rides on the exception because every one of those attempts
        # was billed against the daily cap, and the caller is the only place
        # that can add it up.
        gave_up = RuntimeError(f"gave up after {attempt} attempt(s): {last_error}")
        gave_up.attempts = attempt
        raise gave_up

    def _post(self, body: bytes) -> str:
        request = urllib.request.Request(
            API_URL,
            data=body,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                raw = response.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as error:
            detail = error.read().decode("utf-8", "replace")[:400]
            # Only auth and not-found are worth giving up on immediately.
            # The provider's 400 is "Provider returned error / raw: ERROR",
            # which it also emits transiently under load -- one page hit it at
            # 4s while 119 others went through the same code path fine.
            if error.code in (401, 403, 404):
                raise RuntimeError(f"HTTP {error.code}: {detail}") from error
            raise RetryableError(
                f"HTTP {error.code}: {detail}",
                retry_after_from(error.headers),
                error.code,
            ) from error
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as error:
            raise RetryableError(str(error), None, None) from error

        # A 200 that is nothing but whitespace. While a request is generating,
        # OpenRouter dribbles blank padding down the socket to stop the proxy
        # timing the connection out; if the upstream never finishes, the
        # connection closes with the padding and no JSON behind it. Measured at
        # ~175s and 4 KB of spaces on a two-image request. Reported plainly,
        # because "Expecting value: line 1 column 1" is not a diagnosis.
        if not raw.strip():
            raise RetryableError(
                f"200 with {len(raw)} bytes of keep-alive padding and no body "
                "-- the upstream ran past its own generation limit",
                None,
                None,
            )
        try:
            envelope = json.loads(raw)
        except json.JSONDecodeError as error:
            raise RetryableError(f"{error}: {raw[:200]!r}", None, None) from error

        # A 200 is not a success. This provider reports upstream failures in
        # the body of a 200 -- {"error": {"code": ..., "message": ...}} and no
        # "choices" at all. Indexing straight into ["choices"] turned every one
        # of those into a bare KeyError('choices'), which broke out of the retry
        # ladder as an unrecognised exception AND threw away the only sentence
        # that said what went wrong. Read the error the provider actually sent.
        if "choices" not in envelope:
            failure = envelope.get("error") or envelope
            if isinstance(failure, dict):
                code, message_text = failure.get("code"), failure.get("message", "")
            else:
                code, message_text = None, str(failure)
            detail = f"200 with no choices: {code} {message_text}"[:400]
            if code in (401, 403, 404):
                raise RuntimeError(detail)
            raise RetryableError(detail, None, code if isinstance(code, int) else None)
        message = envelope["choices"][0]["message"]

        content = message.get("content")
        if not content:
            # Observed as a cluster of empty 200s at a uniform ~187s while 60
            # workers were queued: a provider-side timeout, not a token budget
            # (finish_reason says so -- if it ever reads "length", --max-tokens
            # is the lever and more workers are not).
            raise RetryableError(
                "empty content from model "
                f"(finish_reason={message.get('finish_reason')!r})",
                None,
                None,
            )
        return content


def image_part(image: bytes, mime: str) -> dict:
    return {
        "type": "image_url",
        "image_url": {
            "url": f"data:{mime};base64," + base64.b64encode(image).decode("ascii")
        },
    }


class RetryableError(Exception):
    def __init__(
        self, message: str, retry_after: float | None, status: int | None
    ) -> None:
        super().__init__(message)
        self.retry_after = retry_after
        self.status = status


def retry_after_from(headers) -> float | None:
    raw = headers.get("Retry-After")
    if raw:
        try:
            return float(raw)
        except ValueError:
            pass  # HTTP-date form; fall through to the reset header
    reset = headers.get("X-RateLimit-Reset")
    if reset:
        try:  # epoch milliseconds
            return max(0.0, float(reset) / 1000.0 - time.time())
        except ValueError:
            pass
    return None


def parse_json(content: str) -> dict:
    text = content.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n|\n```$", "", text).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # Last resort: the outermost {...} in whatever it said.
        start, end = text.find("{"), text.rfind("}")
        if start == -1 or end <= start:
            raise ValueError(f"no JSON object in response: {text[:200]!r}") from None
        return json.loads(text[start : end + 1])


def validate(analysis: object) -> dict:
    """Reject anything downstream can't cluster. A rejected page is recorded as
    a failure and retried on the next run -- it is never silently kept as a
    page with, say, zero fields, which would read as a real blank."""
    if not isinstance(analysis, dict):
        raise TypeError(f"expected a JSON object, got {type(analysis).__name__}")
    missing = REQUIRED_KEYS - analysis.keys()
    if missing:
        raise ValueError(f"missing key(s): {sorted(missing)}")
    if analysis["page_role"] not in VALID_ROLES:
        raise ValueError(f"unknown page_role {analysis['page_role']!r}")
    fields = analysis["fields"]
    if not isinstance(fields, list) or any(
        not isinstance(f, dict) or "label" not in f for f in fields
    ):
        raise ValueError("fields must be a list of objects with a label")
    return analysis


def validate_batch(payload: object, card_ids: list[str]) -> dict:
    """All-or-nothing: a batch that is missing any requested id is a failed
    batch, not a partial success. Raising ValueError puts it back through the
    retry ladder -- half a batch silently recorded would be indistinguishable
    from pages the model genuinely had nothing to say about."""
    if not isinstance(payload, dict):
        raise TypeError(f"expected a JSON object, got {type(payload).__name__}")
    pages = payload.get("pages", payload)  # tolerate a bare id -> analysis map
    if not isinstance(pages, dict):
        raise TypeError(f"expected 'pages' to be an object, got {type(pages).__name__}")
    missing = [card_id for card_id in card_ids if card_id not in pages]
    if missing:
        raise ValueError(
            f"response covered {len(pages)} of {len(card_ids)} pages; "
            f"missing {missing[:3]}"
        )
    return {card_id: validate(pages[card_id]) for card_id in card_ids}


def completed_ids(results_path: Path, skip_failed: bool) -> set[str]:
    """Card ids not to run again. Failures are retried by default -- most are
    transient, and a permanently broken page costs nothing to re-fail."""
    if not results_path.exists():
        return set()
    done: set[str] = set()
    with results_path.open() as file:
        for line in file:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue  # a torn last line from a hard kill; the page reruns
            if row.get("ok") or skip_failed:
                done.add(row["card_id"])
            else:
                done.discard(row["card_id"])
    return done


def build_jobs(
    input_dir: Path, units: list[str] | None
) -> tuple[list[Page], list[str]]:
    pages: list[Page] = []
    unreadable: list[str] = []
    for unit, pdf in find_unit_pdfs(input_dir):
        if units and unit not in units:
            continue
        try:
            reader = open_unit(pdf)
            pages.extend(unit_pages(unit, pdf, reader))
        except UnreadablePdf as error:
            unreadable.append(str(error))
    return pages, unreadable


def sample_per_unit(pages: list[Page], per_unit: int) -> list[Page]:
    """N pages from every unit, spread evenly through each one.

    Which structures exist is a question about the corpus, and 44 units seen
    shallowly answers it where one unit seen exhaustively does not: within a
    unit the fronts repeat -- 216418 gave 60-62 fields on every one of them --
    so the marginal page from a unit already sampled buys almost nothing, while
    the first page from an unsampled unit can add a whole structure.

    Evenly spread rather than the first N, because the first N pages of a unit
    are its first N records: consecutive, filled in by one clerk in one sitting,
    and the least likely stretch of the unit to disagree with itself.

    Deterministic, so a run interrupted halfway resumes on the same selection.
    """
    by_unit: dict[str, list[Page]] = {}
    for page in pages:
        by_unit.setdefault(page.unit, []).append(page)

    picked: list[Page] = []
    for in_unit in by_unit.values():
        if per_unit >= len(in_unit):
            picked.extend(in_unit)
            continue
        step = len(in_unit) / per_unit
        picked.extend(in_unit[int(i * step)] for i in range(per_unit))
    return sorted(picked, key=lambda page: page.card_id)


def run_analysis(
    *,
    input_dir: Path,
    output: Path,
    model: str,
    workers: int,
    rpm: float,
    max_tokens: int,
    reasoning_effort: str,
    units: list[str] | None,
    limit: int | None,
    skip_failed: bool,
    dry_run: bool,
    batch: int = 1,
    max_requests: int = 0,
    per_unit: int = 0,
) -> None:
    pages, unreadable = build_jobs(input_dir, units)
    for problem in unreadable:
        print(f"UNREADABLE UNIT: {problem}", file=sys.stderr)

    corpus = len(pages)
    if per_unit:
        pages = sample_per_unit(pages, per_unit)

    # --limit picks the pages, and only then does resume subtract the ones
    # already done. The other order -- take the first N *not yet done* -- makes
    # a limited run analyse a different set of pages every time it is resumed,
    # which is fine for a smoke test and silently fatal for a comparison: two
    # arms interrupted at different points stop covering the same cards.
    done = completed_ids(output, skip_failed)
    todo = [
        page for page in (pages[:limit] if limit else pages) if page.card_id not in done
    ]

    requests = -(-len(todo) // batch)  # what the daily cap actually counts
    print(
        f"{len(pages)} pages across {len({p.unit for p in pages})} readable units, "
        + (f"sampled {per_unit}/unit from {corpus}, " if per_unit else "")
        + f"{len(unreadable)} unreadable; {len(done)} already done, {len(todo)} to run"
        + (f" in {requests} requests of {batch}" if batch > 1 else "")
    )
    if dry_run or not todo:
        return

    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        raise SystemExit("OPENROUTER_API_KEY is not set (see .env.example)")

    client = Client(
        api_key=api_key,
        model=model,
        gate=RateGate(rpm),
        max_tokens=max_tokens,
        reasoning_effort=reasoning_effort,
        # A batch is K times the work behind one socket. Timing out is the
        # expensive failure -- the request is billed and produces nothing -- so
        # the clock grows with the batch, but sublinearly: a genuinely stuck
        # request should not hold a worker for the better part of an hour.
        timeout=TIMEOUT_SECONDS + 60 * (batch - 1),
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    write_lock = threading.Lock()
    counts = {"ok": 0, "failed": 0, "requests": 0}
    spent = {"reserved": 0}
    stopped_early = False
    wall_start = time.monotonic()

    with output.open("a") as results:
        # One writer at a time. Four concurrent runs each computed the same
        # todo list from an empty results file and spent a whole day's request
        # budget re-analysing the same pages; completed_ids reads the file once
        # at startup and cannot see a run that is still going. flock releases
        # itself when the process dies, so a hard kill leaves no stale lock.
        try:
            fcntl.flock(results, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            raise SystemExit(
                f"another analyze run is already writing to {output} -- "
                "wait for it, or point --results somewhere else"
            ) from None

        def record(row: dict) -> None:
            with write_lock:
                results.write(json.dumps(row) + "\n")
                results.flush()  # append-and-flush per row is what makes Ctrl-C safe
                counts["ok" if row["ok"] else "failed"] += 1
                done_now = counts["ok"] + counts["failed"]
                print(
                    f"[{done_now}/{len(todo)}] {row['card_id']} "
                    + (
                        f"{row['analysis']['page_role']} "
                        f"{len(row['analysis']['fields'])} fields"
                        if row["ok"]
                        else f"FAILED {row['error']}"
                    )
                    + f" ({row['elapsed_s']:.1f}s)",
                    flush=True,
                )

        def run_batch(items: list[tuple[Page, object, str | None]]) -> None:
            """One request covering `items`; one row written per page either way.

            A page whose scan could not be extracted never reaches the model,
            so it is dropped from the request and recorded with its own
            extraction error -- it must not cost the rest of the batch.
            """
            start = time.monotonic()
            sendable = [(page, image) for page, image, _ in items if image is not None]
            analyses: dict[str, dict] = {}
            attempts, call_error = 0, None
            request_id = uuid.uuid4().hex[:12] if sendable else None
            if sendable:
                try:
                    if len(sendable) == 1:
                        # The unbatched path, byte-for-byte: PROMPT, not
                        # batch_prompt. The baseline arm of a batching
                        # comparison has to be the prompt already in service.
                        page, image = sendable[0]
                        analysis, attempts = client.analyse(image.data, image.mime)
                        analyses = {page.card_id: analysis}
                    else:
                        analyses, attempts = client.analyse_batch(
                            [(p.card_id, i.data, i.mime) for p, i in sendable]
                        )
                except Exception as failure:  # noqa: BLE001 -- one batch must not kill the pool
                    call_error = str(failure)[:500]
                    attempts = getattr(failure, "attempts", client.attempts)
            elapsed = time.monotonic() - start
            with write_lock:
                # Every attempt is billed against the daily cap, including the
                # ones that timed out or came back unparseable. Only the first
                # was reserved at submit time; charge the retries on top so the
                # budget check sees what was actually spent.
                counts["requests"] += attempts
                spent["reserved"] += max(0, attempts - 1)

            for page, image, extraction_error in items:
                analysis = analyses.get(page.card_id)
                record(
                    {
                        "card_id": page.card_id,
                        "unit": page.unit,
                        "pdf": str(page.pdf),
                        "page_number": page.page_number,
                        "model": model,
                        "ok": analysis is not None,
                        "error": extraction_error or (None if analysis else call_error),
                        "attempts": attempts,
                        # Wall time for the whole request, repeated on each of
                        # its pages -- divide by "batch" for per-page cost.
                        "elapsed_s": elapsed,
                        "batch": len(sendable),
                        # Which pages shared a request, so the billed cost of a
                        # run can be recovered from the file and not just the
                        # summary line: sum(attempts) over distinct request_ids.
                        "request_id": request_id,
                        "image_count": image.image_count if image else None,
                        "analysis": analysis,
                    }
                )

        # The main thread reads page bytes and the semaphore caps how many
        # requests are in flight, so peak memory is (workers * 2 * batch) scans,
        # not the archive.
        # ponytail: at batch 10 and 32 workers that is ~320 MB of JPEG; tighten
        # the semaphore to `workers + 4` if a larger batch starts to hurt.
        in_flight = threading.Semaphore(workers * 2)

        def submit(pool, items) -> bool:
            """False once the run has spent its --max-requests allowance.

            The allowance is reserved before the request goes out and topped up
            with whatever retries it turns out to need, so a run cannot discover
            it is over budget only after the fact -- which is the only kind of
            budget that is any use against a cap that resets once a day.
            """
            with write_lock:
                if max_requests and spent["reserved"] >= max_requests:
                    return False
                spent["reserved"] += 1
            in_flight.acquire()
            future = pool.submit(run_batch, items)
            future.add_done_callback(lambda _: in_flight.release())
            return True

        with ThreadPoolExecutor(max_workers=workers) as pool:
            reader = None
            current_pdf = None
            pending: list[tuple[Page, object, str | None]] = []
            for page in todo:
                if page.pdf != current_pdf:
                    reader, current_pdf = open_unit(page.pdf), page.pdf
                try:
                    image, error = page_image(reader, page.page_number), None
                except Exception as failure:  # noqa: BLE001 -- missing/odd image XObject
                    image, error = None, f"image extraction: {failure}"
                pending.append((page, image, error))
                if len(pending) == batch:
                    if not submit(pool, pending):
                        stopped_early = True
                        break
                    pending = []
            if pending and not stopped_early:
                submit(pool, pending)

    elapsed = time.monotonic() - wall_start
    rate = counts["ok"] / elapsed * 60 if elapsed else 0
    print(
        f"\n{counts['ok']} ok, {counts['failed']} failed in {elapsed / 60:.1f} min "
        f"({rate:.1f} pages/min). Results appended to {output}"
    )
    print(
        f"{counts['requests']} request(s) spent against the 1,000/day cap "
        f"at --batch {batch}"
        + (f", {counts['requests'] - requests} of them retries" if requests else "")
    )
    if stopped_early:
        print(
            f"STOPPED at the --max-requests {max_requests} allowance with "
            f"{len(todo) - counts['ok'] - counts['failed']} page(s) unsent -- "
            "rerun the same command to continue where it left off"
        )
    gate = client.gate
    if gate.pauses:
        share = gate.paused_seconds / elapsed if elapsed else 0
        print(
            f"Throttled {gate.pauses} time(s), {gate.paused_seconds / 60:.1f} min "
            f"of enforced waiting ({share:.0%} of the run)"
            # Only worth acting on when waiting is a real share of the wall
            # clock. A couple of 429s inside a latency-bound run means the
            # backoff did its job, not that --rpm is too high.
            + (f" -- lower --rpm toward {rate:.0f}" if share > 0.2 else "")
        )
    else:
        print(f"No 429s at --rpm {rpm} with {workers} workers")
    remaining = len(pages) - len(done) - counts["ok"]
    if remaining > 0 and rate > 0:
        print(
            f"{remaining} pages left -- about {remaining / rate / 60:.1f} h at this rate"
        )

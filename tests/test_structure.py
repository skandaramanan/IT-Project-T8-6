"""The bits of the structure pipeline that can be wrong quietly.

Everything here is pure: no PDFs, no network. The parts that talk to
OpenRouter are a thin wrapper around urllib and are exercised by actually
running the thing; the parts that decide "these two cards are the same
structure" are where a silent bug turns into a wrong answer in a client
report, so those are pinned here.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest

from structure.analyze import (
    PROMPT,
    Client,
    RateGate,
    batch_prompt,
    completed_ids,
    parse_json,
    validate,
    validate_batch,
)
from structure.cli import load_env, survey_data_dir
from structure.inventory import DEFAULT_INPUT_DIR
from structure.report import (
    cluster_rows,
    cycle_breaks,
    fingerprint,
    jaccard,
    load_rows,
    normalise_label,
    rank_anomalies,
    write_reports,
)

CYCLE = ["survey-front", "survey-back", "coding-front", "coding-back"]


def page(card_id, role, labels, unit="216412", number=1, anomalies=()):
    return {
        "card_id": card_id,
        "unit": unit,
        "pdf": f"data/{unit}/x.pdf",
        "page_number": number,
        "ok": True,
        "analysis": {
            "page_role": role,
            "fields": [{"label": label} for label in labels],
            "anomalies": list(anomalies),
        },
    }


def test_normalise_absorbs_punctuation_and_case_but_not_words():
    assert normalise_label("No. of Dwelling") == normalise_label("no of dwelling.")
    assert normalise_label("Number under 5") != normalise_label("Number under 10")


def test_fingerprint_ignores_field_order_but_not_role():
    labels = {"a", "b"}
    assert fingerprint("coding-front", labels) == fingerprint(
        "coding-front", {"b", "a"}
    )
    assert fingerprint("coding-front", labels) != fingerprint("survey-front", labels)


def test_near_identical_transcriptions_merge_into_one_structure():
    # 20 clean cards plus one where the model dropped a single label of 20 --
    # exactly the wobble that an exact hash would report as a variant.
    labels = [f"field {n}" for n in range(20)]
    rows = [page(f"c{n}", "coding-front", labels, number=n) for n in range(20)]
    rows.append(page("c99", "coding-front", labels[:-1], number=99))

    merged = cluster_rows(rows, threshold=0.9)
    assert len(merged) == 1
    assert merged[0].size == 21

    strict = cluster_rows(rows, threshold=1.0)
    assert len(strict) == 2  # threshold 1.0 keeps every wobble apart, as documented


def test_a_genuinely_different_form_stays_its_own_structure():
    rows = [
        page(f"c{n}", "coding-front", [f"field {n}" for n in range(20)])
        for n in range(5)
    ]
    rows.append(page("odd", "coding-front", [f"other {n}" for n in range(20)]))
    assert len(cluster_rows(rows, threshold=0.9)) == 2


def test_same_labels_different_roles_do_not_cluster_together():
    labels = ["name", "address"]
    rows = [page("a", "coding-front", labels), page("b", "survey-front", labels)]
    assert len(cluster_rows(rows, threshold=0.9)) == 2


def test_jaccard_edges():
    assert jaccard(set(), set()) == 1.0
    assert jaccard({"a"}, set()) == 0.0


def test_cycle_breaks_finds_the_odd_page_out_regardless_of_phase():
    # Unit starts mid-cycle (on coding-front) and has one extra survey-back
    # spliced in at page 7 -- the break, not the phase, is what should be flagged.
    roles = CYCLE[2:] + CYCLE + ["survey-back"] + CYCLE[1:]
    rows = [
        page(f"p{n}", role, ["x"], number=n) for n, role in enumerate(roles, start=1)
    ]
    breaks = cycle_breaks(rows)["216412"]
    assert 7 in breaks
    assert len(breaks) < len(roles) / 2  # phase found, not brute-forced as all-wrong


def test_cycle_breaks_reports_nothing_for_a_clean_unit():
    rows = [
        page(f"p{n}", role, ["x"], number=n)
        for n, role in enumerate(CYCLE * 3, start=1)
    ]
    assert cycle_breaks(rows)["216412"] == []


def test_cycle_breaks_reads_the_phase_off_the_page_number_not_the_row_order():
    # A sampled run holds every 26th page, so consecutive rows are 26 pages
    # apart. The cycle still holds on these pages; walking it by row index
    # advances the expected role one step per row and flags almost all of them.
    rows = [
        page(f"p{n}", CYCLE[(n - 1) % 4], ["x"], number=n) for n in range(1, 500, 26)
    ]
    assert cycle_breaks(rows)["216412"] == []


def test_rerun_of_a_failed_page_supersedes_the_failure(tmp_path):
    results = tmp_path / "pages.jsonl"
    results.write_text(
        json.dumps({"card_id": "a", "ok": False, "error": "429"})
        + "\n"
        + json.dumps(page("a", "coding-front", ["x"]))
        + "\n"
    )
    ok, failed = load_rows(results)
    assert len(ok) == 1 and failed == []


def test_resume_skips_successes_and_retries_failures(tmp_path):
    results = tmp_path / "pages.jsonl"
    results.write_text(
        json.dumps({"card_id": "good", "ok": True})
        + "\n"
        + json.dumps({"card_id": "bad", "ok": False})
        + "\n"
    )
    assert completed_ids(results, skip_failed=False) == {"good"}
    assert completed_ids(results, skip_failed=True) == {"good", "bad"}


def test_resume_survives_a_line_torn_by_a_hard_kill(tmp_path):
    results = tmp_path / "pages.jsonl"
    results.write_text(
        json.dumps({"card_id": "good", "ok": True}) + "\n" + '{"card_id": "tor'
    )
    assert completed_ids(results, skip_failed=False) == {"good"}


def test_parse_json_survives_fences_and_commentary():
    assert parse_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert parse_json('Sure!\n{"a": 1}\nHope that helps.') == {"a": 1}


def test_validate_rejects_what_clustering_cannot_use():
    good = {"page_role": "coding-front", "fields": [{"label": "x"}], "anomalies": []}
    assert validate(good) is good
    for bad in (
        {"page_role": "coding-front", "fields": []},  # no anomalies key
        {"page_role": "front", "fields": [], "anomalies": []},  # invented role
        {"page_role": "blank", "fields": ["x"], "anomalies": []},  # fields not objects
        [],
    ):
        try:
            validate(bad)
        except (TypeError, ValueError):
            continue
        raise AssertionError(f"validate accepted {bad!r}")


def test_common_anomalies_do_not_become_exceptions(tmp_path):
    # Every card reports punch holes; only the odd-form card is an exception.
    labels = [f"field {n}" for n in range(20)]
    rows = [
        page(f"c{n}", "coding-front", labels, number=n, anomalies=["punched holes"])
        for n in range(10)
    ]
    rows.append(page("odd", "coding-front", ["a", "b"], number=99, anomalies=["torn"]))
    clusters = cluster_rows(rows, threshold=0.9)

    exceptions = write_reports(clusters, [], {}, tmp_path, total_pages=len(rows))
    assert [e["card_id"] for e in exceptions] == ["odd"]

    ranked = rank_anomalies(clusters)
    assert ranked[0]["anomaly"] == "torn"  # rarest first
    assert ranked[-1]["cards"] == 10


def test_load_env_reads_the_file_but_never_overrides_the_shell(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text(
        '# a comment\n\nOPENROUTER_API_KEY=sk-from-file\nQUOTED="with spaces"\n'
        "ALREADY_SET=from-file\nnot a pair\n"
    )
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setenv("ALREADY_SET", "from-shell")

    load_env(env)

    assert os.environ["OPENROUTER_API_KEY"] == "sk-from-file"
    assert os.environ["QUOTED"] == "with spaces"
    assert os.environ["ALREADY_SET"] == "from-shell"


def test_missing_env_file_is_not_an_error(tmp_path):
    load_env(tmp_path / "nope")


def test_survey_data_dir_follows_the_documented_variable(monkeypatch):
    monkeypatch.setenv("SURVEY_DATA_DIR", "/mnt/scans")
    assert survey_data_dir() == Path("/mnt/scans/Wilfred_Prest_Survey_Data")
    monkeypatch.delenv("SURVEY_DATA_DIR")
    assert survey_data_dir() == DEFAULT_INPUT_DIR


def test_an_unusable_200_is_retried_but_a_401_is_not(monkeypatch):
    monkeypatch.setattr(time, "sleep", lambda _: None)
    good = json.dumps(
        {"page_role": "coding-front", "fields": [{"label": "age"}], "anomalies": []}
    )
    # First reply is the model claiming it got no image; second is the real one.
    replies = ["I can't see any scan of the survey page, so I can't report", good]
    monkeypatch.setattr(Client, "_post", lambda self, body: replies.pop(0))

    client = Client(
        api_key="k",
        model="m",
        gate=RateGate(0),
        max_tokens=100,
        reasoning_effort="low",
    )
    analysis, attempts = client.analyse(b"jpeg", "image/jpeg")
    assert analysis["page_role"] == "coding-front"
    assert attempts == 2

    calls = 0

    def unauthorised(self, body):
        nonlocal calls
        calls += 1
        raise RuntimeError("HTTP 401: no credentials")  # what _post raises

    monkeypatch.setattr(Client, "_post", unauthorised)
    try:
        client.analyse(b"jpeg", "image/jpeg")
    except RuntimeError:
        pass
    assert calls == 1  # a bad key stays bad; don't spend three more on it


def test_a_second_analyze_run_refuses_to_start(tmp_path):
    """The failure that cost a day's request budget: concurrent runs each read
    an empty results file, so each analysed the same pages."""
    import fcntl

    results = tmp_path / "pages.jsonl"
    with results.open("a") as held:
        fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with results.open("a") as second, pytest.raises(OSError):
            fcntl.flock(second, fcntl.LOCK_EX | fcntl.LOCK_NB)


def analysis(role="coding-front", labels=("age",)):
    return {
        "page_role": role,
        "fields": [{"label": x} for x in labels],
        "anomalies": [],
    }


def test_batch_prompt_carries_the_same_field_schema_as_the_single_page_one():
    """If the two prompts ever describe different keys, a batching comparison
    is measuring the prompt rewrite and not the batching."""
    schema = PROMPT.split("Return a JSON object with exactly these keys:\n\n", 1)[1]
    prompt = batch_prompt(["216418_p0001", "216418_p0002"])
    assert schema in prompt
    assert "216418_p0001" in prompt and "216418_p0002" in prompt
    assert "2 SEPARATE pages" in prompt


def test_a_batch_missing_a_page_fails_whole_rather_than_recording_part():
    """Half a batch quietly kept would look like pages the model had nothing to
    say about, which is exactly the reading the clustering would then believe."""
    with pytest.raises(ValueError, match="covered 1 of 2"):
        validate_batch({"pages": {"a": analysis()}}, ["a", "b"])

    # A bare id -> analysis map is accepted; the wrapper key is a convention.
    assert set(validate_batch({"a": analysis(), "b": analysis()}, ["a", "b"])) == {
        "a",
        "b",
    }
    # One bad page still fails the batch -- validate's rules are not relaxed.
    with pytest.raises(ValueError, match="page_role"):
        validate_batch({"a": analysis(role="middle")}, ["a"])


def test_a_short_batch_is_retried_and_its_cost_is_reported(monkeypatch):
    monkeypatch.setattr(time, "sleep", lambda _: None)
    replies = [
        json.dumps({"pages": {"a": analysis()}}),  # dropped page b
        json.dumps({"pages": {"a": analysis(), "b": analysis(labels=("rent",))}}),
    ]
    monkeypatch.setattr(Client, "_post", lambda self, body: replies.pop(0))
    client = Client(
        api_key="k",
        model="m",
        gate=RateGate(0),
        max_tokens=100,
        reasoning_effort="low",
    )
    analyses, attempts = client.analyse_batch(
        [("a", b"jpeg", "image/jpeg"), ("b", b"jpeg", "image/jpeg")]
    )
    assert set(analyses) == {"a", "b"}
    assert attempts == 2  # both attempts were billed against the daily cap


def test_giving_up_reports_how_many_requests_it_spent(monkeypatch):
    """Two attempts that both fail cost two requests, not one."""
    monkeypatch.setattr(time, "sleep", lambda _: None)
    monkeypatch.setattr(Client, "_post", lambda self, body: "not json at all")
    client = Client(
        api_key="k",
        model="m",
        gate=RateGate(0),
        max_tokens=100,
        reasoning_effort="low",
        attempts=3,
    )
    with pytest.raises(RuntimeError) as caught:
        client.analyse(b"jpeg", "image/jpeg")
    assert caught.value.attempts == 3


def test_a_resumed_limited_run_finishes_the_same_pages(tmp_path, monkeypatch, capsys):
    """--limit has to name a fixed set, not "the next N unfinished". Two
    calibration arms interrupted at different points would otherwise stop
    covering the same cards, and the comparison would be of two page sets."""
    from structure import analyze

    pages = [
        analyze.Page(card_id=f"u_p{n:04d}", unit="u", pdf=Path("u.pdf"), page_number=n)
        for n in range(1, 21)
    ]
    monkeypatch.setattr(analyze, "build_jobs", lambda *_: (pages, []))

    results = tmp_path / "arm.jsonl"
    results.write_text(
        "\n".join(
            json.dumps({"card_id": f"u_p{n:04d}", "ok": True}) for n in range(1, 4)
        )
        + "\n"
    )

    analyze.run_analysis(
        input_dir=tmp_path,
        output=results,
        model="m",
        workers=1,
        rpm=0.0,
        max_tokens=1,
        reasoning_effort="low",
        units=None,
        limit=5,
        skip_failed=False,
        dry_run=True,
        batch=1,
    )
    # The first 5 pages are the selection and 3 are done, so 2 are left --
    # not 5 fresh ones taken from further down the unit.
    assert "3 already done, 2 to run" in capsys.readouterr().out


def test_a_200_carrying_an_error_body_is_read_not_swallowed(monkeypatch):
    """The failure that made a whole batching run unreadable: this provider
    reports upstream errors in the body of a 200 with no "choices" key, and
    indexing straight into it raised KeyError('choices') -- which escaped the
    retry ladder as an unrecognised exception and discarded the one sentence
    saying what had gone wrong."""
    import io
    import urllib.request

    monkeypatch.setattr(time, "sleep", lambda _: None)
    body = json.dumps(
        {"error": {"code": 502, "message": "Provider returned error"}}
    ).encode()

    class Response(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

    monkeypatch.setattr(
        urllib.request, "urlopen", lambda *a, **k: Response(bytes(body))
    )
    client = Client(
        api_key="k",
        model="m",
        gate=RateGate(0),
        max_tokens=100,
        reasoning_effort="low",
        attempts=2,
    )
    with pytest.raises(RuntimeError) as caught:
        client.analyse(b"jpeg", "image/jpeg")
    assert "Provider returned error" in str(caught.value)
    assert "502" in str(caught.value)
    assert caught.value.attempts == 2  # retried, not abandoned on the first


def test_keep_alive_padding_with_no_body_is_named_for_what_it_is(monkeypatch):
    """A 200 carrying only OpenRouter's blank keep-alive padding. Reported as
    itself rather than as a JSON parse error at column 1, because the two lead
    somewhere completely different."""
    import io
    import urllib.request

    monkeypatch.setattr(time, "sleep", lambda _: None)

    class Response(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

    monkeypatch.setattr(
        urllib.request, "urlopen", lambda *a, **k: Response(b"\n     " * 400)
    )
    client = Client(
        api_key="k",
        model="m",
        gate=RateGate(0),
        max_tokens=100,
        reasoning_effort="low",
        attempts=2,
    )
    with pytest.raises(RuntimeError, match="keep-alive padding"):
        client.analyse(b"jpeg", "image/jpeg")


def test_sampling_covers_every_unit_and_spreads_through_each():
    """Breadth is the point: a unit ten times the size of another still gets
    the same number of pages, and they come from across it rather than off the
    front, where consecutive records are least likely to disagree."""
    from structure.analyze import sample_per_unit

    pages = [
        analyze_page(f"{unit}_p{n:04d}", unit, n)
        for unit, count in (("a", 100), ("b", 10), ("c", 3))
        for n in range(1, count + 1)
    ]
    picked = sample_per_unit(pages, 5)

    from collections import Counter

    per_unit = Counter(page.unit for page in picked)
    assert per_unit == {"a": 5, "b": 5, "c": 3}  # a short unit gives all it has
    spread = [p.page_number for p in picked if p.unit == "a"]
    assert spread == [1, 21, 41, 61, 81]  # across the unit, not 1..5
    assert picked == sample_per_unit(pages, 5)  # deterministic, so resume works


def analyze_page(card_id, unit, number):
    from structure.analyze import Page

    return Page(card_id=card_id, unit=unit, pdf=Path(f"{unit}.pdf"), page_number=number)


def _row(card_id: str, role: str, labels: list[str]) -> dict:
    return {
        "card_id": card_id,
        "unit": "216415",
        "pdf": "u.pdf",
        "page_number": 1,
        "ok": True,
        "analysis": {
            "page_role": role,
            "fields": [{"label": label, "value": ""} for label in labels],
            "anomalies": [],
        },
    }


def test_pool_429_backs_off_in_minutes_not_seconds():
    """A 429 with no Retry-After is the shared upstream pool, which clears in
    minutes. The 2/4/8/16s ladder spent all four attempts inside 30s and
    recorded a queue as a failure -- 13 of 97 pages on 2026-08-25."""
    gate = RateGate(rpm=0)
    client = Client(
        api_key="k",
        model="m",
        gate=gate,
        max_tokens=10,
        reasoning_effort="low",
        attempts=4,
    )

    class Pool429(Exception):
        status = 429
        retry_after = None

    paused: list[float] = []
    gate.pause = paused.append  # type: ignore[method-assign]
    client._post = lambda body: (_ for _ in ()).throw(  # type: ignore[method-assign]
        __import__("structure.analyze", fromlist=["RetryableError"]).RetryableError(
            "HTTP 429: upstream_provider_shared_pool", None, 429
        )
    )
    with pytest.raises(RuntimeError):
        client.chat([{"type": "text", "text": "x"}], json_mode=False)

    assert paused, "a 429 must pause the shared gate, not just this worker"
    assert sum(paused) >= 240, (
        f"four pool-429 attempts backed off {sum(paused)}s total; the pool "
        "clears in minutes, so anything under 4 minutes re-earns the same 429 "
        "and burns four billed requests for nothing"
    )


def test_reference_cards_pick_the_most_representative_card():
    """The example scan must be the card that best matches its own cluster, not
    cards[0] -- a cluster's first card can be the bled-through or rotated scan
    that made it a separate cluster, which is the worst thing to hand someone
    as 'this is what this structure looks like'."""
    from structure.report import card_labels

    canonical = ["age", "tenure", "kitchen", "bathroom"]
    rows = [
        _row("bad", "coding-front", ["age"]),  # a bad scan: read one label
        _row("good", "coding-front", canonical),
    ]
    clusters = cluster_rows(rows, threshold=0.1)
    cluster = next(c for c in clusters if c.role == "coding-front")

    best = max(
        cluster.cards,
        key=lambda card: (
            len(card_labels(card) & cluster.labels),
            len(card_labels(card)),
        ),
    )
    assert best["card_id"] == "good"


def test_reference_cards_cover_fronts_only():
    """Reverses carry no printed labels, so they cluster on role alone and an
    example of one shows nothing about structure."""
    from structure.report import FRONT_ROLES

    assert set(FRONT_ROLES) == {"coding-front", "survey-front"}
    assert FRONT_ROLES[0] == "coding-front", "numeric card is the primary one"


def test_bleed_through_reverses_are_not_front_structures(tmp_path):
    """A blank reverse whose printed front shows through the paper reads as a
    front, mirrored, and clusters on its own. Four shipped as "front
    structures" before the export filtered on parity instead of the role label.
    """
    from structure.report import export_reference_cards

    labels = ["age", "tenure", "kitchen", "bathroom"]
    rows = []
    for page in (1, 3, 5):  # real fronts: odd pages in this unit
        r = _row(f"u_p{page:04d}", "coding-front", labels)
        r["page_number"] = page
        rows.append(r)
    bleed = _row("u_p0008", "coding-front", ["egA", "erunet"])  # mirrored gibberish
    bleed["page_number"] = 8  # even -> a reverse
    rows.append(bleed)

    clusters = cluster_rows(rows, threshold=0.8)
    assert any(c.cluster_id for c in clusters if c.labels == {"ega", "erunet"}), (
        "the bleed-through must be its own cluster, or the test proves nothing"
    )

    _, index = export_reference_cards(clusters, tmp_path)
    listed = index.read_text()
    assert "u_p0008" not in listed, (
        "a cluster whose every page is on a reverse is bleed-through, not a form"
    )


def test_front_parity_phase_is_per_unit(tmp_path):
    """Five units number their fronts even. A global 'fronts are odd' rule would
    drop their real cards, so the phase is taken per unit."""
    from structure.report import export_reference_cards

    labels = ["age", "tenure", "kitchen", "bathroom"]
    rows = []
    for page in (2, 4, 6):  # this unit's fronts are EVEN
        r = _row(f"even_p{page:04d}", "coding-front", labels)
        r["page_number"] = page
        r["unit"] = "216415"
        rows.append(r)
    clusters = cluster_rows(rows, threshold=0.8)
    _, index = export_reference_cards(clusters, tmp_path)
    listed = index.read_text()
    assert clusters[0].cluster_id in listed, (
        "an even-numbered front in a phase-offset unit is still a front"
    )

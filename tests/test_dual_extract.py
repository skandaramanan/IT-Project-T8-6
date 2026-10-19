"""Pairing two extractors' readings: what counts as agreement, and what doesn't.

The class that matters most is NO_SECOND_OPINION. Every other mistake here
makes a confidence score slightly wrong; collapsing a missing arm into AGREE
makes it confidently wrong, on exactly the cards where a reviewer most needs
the truth. IT-99 AC4 exists for that case and these tests are its guard.

No API and no data/ -- both arms are constructed as plain dicts, or as text
files under tmp_path.
"""

import json
from pathlib import Path

import pytest

from dual_extract import (
    fetch_command,
    load_arm,
    missing_pages,
    pair_cards,
    summarise,
)
from survey.confidence.agreement import (
    AGREE,
    BOTH_BLANK,
    DISAGREE,
    NO_SECOND_OPINION,
    ONE_BLANK,
    SCHEMA_FIELD_NAMES,
    classify,
    compare_fields,
)

FIELDS = ["Municipality", "Weekly Rent", "Garden"]


# --- the five classes -------------------------------------------------------


@pytest.mark.parametrize(
    "first, second, expected",
    [
        ("56", "56", AGREE),
        ("3", "8", DISAGREE),
        ("3", "", ONE_BLANK),
        ("", "3", ONE_BLANK),
        ("", "", BOTH_BLANK),
        (None, None, BOTH_BLANK),  # explicit nulls: both read no code
        ("-", "B", BOTH_BLANK),  # transcriber's dash vs the coder's void mark
    ],
)
def test_each_class(first, second, expected):
    assert classify(first, second) == expected


@pytest.mark.parametrize(
    "first, second",
    [("1", "1."), ("15", "1.5."), ("0", "O"), ("1", "L"), (" 3 ", "3")],
)
def test_noise_is_not_disagreement(first, second):
    """The artefacts IT-98 AC2 lists: leader dots, digit lookalikes, whitespace."""
    assert classify(first, second) == AGREE


@pytest.mark.parametrize("first, second", [("04", "4"), ("4", "04"), ("060", "60")])
def test_leading_zero_split_is_a_real_disagreement(first, second):
    """IT-98 AC2b. Under a fixed-width code book these are different codes, so
    one model has misread a real value -- that has to pull confidence down, not
    be normalised away (D011)."""
    assert classify(first, second) == DISAGREE


# --- a missing arm ----------------------------------------------------------


def test_missing_second_arm_is_never_agreement():
    """The one that would inflate every downstream confidence number."""
    paired = compare_fields({"Municipality": "56"}, None, FIELDS)
    assert {f["agreement"] for f in paired.values()} == {NO_SECOND_OPINION}


def test_missing_arm_beats_both_blank():
    """Two models agreeing a card is empty and one model never answering are
    different claims. A run that half-failed must not read as a clean one."""
    absent = compare_fields({}, None, FIELDS)
    blank = compare_fields({"Garden": ""}, {"Garden": None}, FIELDS)
    assert absent["Garden"]["agreement"] == NO_SECOND_OPINION
    assert blank["Garden"]["agreement"] == BOTH_BLANK


def test_missing_first_arm_is_handled_too():
    paired = compare_fields(None, {"Municipality": "56"}, FIELDS)
    assert paired["Municipality"]["agreement"] == NO_SECOND_OPINION
    assert paired["Municipality"]["b_raw"] == "56"


# --- shape ------------------------------------------------------------------


def test_every_schema_field_is_emitted():
    """A card is 62 fields whatever the models returned, so a field one model
    dropped is visible as a comparison rather than absent (D011's argument)."""
    paired = compare_fields({"Municipality": "56"}, {"Municipality": "56"})
    assert len(paired) == 62
    assert set(paired) == set(SCHEMA_FIELD_NAMES)
    assert paired["Weekly Rent"]["agreement"] == NO_SECOND_OPINION


def test_raw_readings_are_preserved_unmodified():
    """AC4: a disputed field traces back to what each model actually said,
    without re-parsing the raw response blob."""
    paired = compare_fields({"Municipality": "5.6."}, {"Municipality": "56"}, FIELDS)
    field = paired["Municipality"]
    assert (field["a_raw"], field["b_raw"]) == ("5.6.", "56")
    assert (field["a"], field["b"]) == ("56", "56")  # normalised alongside, not instead
    assert field["agreement"] == AGREE


# --- reading both arms off disk ---------------------------------------------


def _write(root, model, page_id, payload):
    raw = root / model / "raw"
    raw.mkdir(parents=True, exist_ok=True)
    (raw / f"{page_id}.txt").write_text(
        payload if isinstance(payload, str) else json.dumps(payload)
    )


def test_load_arm_distinguishes_an_unusable_answer_from_no_answer(tmp_path):
    """A model that answered unusably is None; a card never answered is absent.
    Both pair as no_second_opinion, but only one is worth re-requesting."""
    _write(tmp_path, "a", "p1", {"Municipality": "56"})
    _write(tmp_path, "a", "p2", "the model apologised instead of answering")
    fields, _ = load_arm(tmp_path, "a")
    assert fields["p1"] == {"Municipality": "56"}
    assert fields["p2"] is None
    assert "p3" not in fields


def test_pair_cards_takes_the_union_not_the_intersection(tmp_path):
    """A card only one arm reached still belongs in the output. Intersecting
    would make a half-failed run look complete."""
    _write(tmp_path, "a", "p1", {"Municipality": "56"})
    _write(tmp_path, "a", "p2", {"Municipality": "27"})
    _write(tmp_path, "b", "p1", {"Municipality": "56"})

    records = {r["page_id"]: r for r in pair_cards("a", "b", tmp_path, FIELDS)}
    assert set(records) == {"p1", "p2"}
    assert records["p1"]["fields"]["Municipality"]["agreement"] == AGREE
    assert records["p2"]["fields"]["Municipality"]["agreement"] == NO_SECOND_OPINION
    assert records["p2"]["models"] == {"a": "a", "b": "b"}


def test_pair_cards_keeps_the_sheet_order(tmp_path):
    """The sheet is the authoritative card list, so the paired output follows
    it rather than the alphabet -- otherwise the JSON cannot be read alongside
    the sheet it came from. Duplicates in the list collapse."""
    for page_id in ("p3", "p1", "p2"):
        _write(tmp_path, "a", page_id, {"Municipality": "56"})
        _write(tmp_path, "b", page_id, {"Municipality": "56"})

    records = pair_cards("a", "b", tmp_path, FIELDS, page_ids=["p3", "p1", "p3", "p2"])
    assert [r["page_id"] for r in records] == ["p3", "p1", "p2"]


def test_counts_add_up_to_the_field_count(tmp_path):
    _write(tmp_path, "a", "p1", {"Municipality": "56", "Weekly Rent": "04"})
    _write(tmp_path, "b", "p1", {"Municipality": "56", "Weekly Rent": "4"})
    record = pair_cards("a", "b", tmp_path, FIELDS)[0]
    assert sum(record["counts"].values()) == len(FIELDS)
    assert record["counts"] == {AGREE: 1, DISAGREE: 1, NO_SECOND_OPINION: 1}


# --- filling in what's missing (step 4, AC5) --------------------------------


def test_missing_pages_lists_only_what_has_no_reading(tmp_path):
    _write(tmp_path, "a", "p1", {"Municipality": "56"})
    _write(tmp_path, "a", "p3", "unparseable, but the model did answer")
    # p3 has a file, so it is not missing -- re-requesting it would spend quota
    # to learn what load_arm already knows: the answer was unusable.
    assert missing_pages(tmp_path, "a", ["p1", "p2", "p3", "p4"]) == ["p2", "p4"]


def test_missing_pages_is_everything_when_the_arm_never_ran(tmp_path):
    assert missing_pages(tmp_path, "never-run", ["p1", "p2"]) == ["p1", "p2"]


def test_fetch_command_limits_the_run_to_the_missing_cards():
    """A wrong flag here fails silently as a full re-run, which on a 20/day cap
    is a day of quota."""
    command = fetch_command("gemini", ["p2", "p4"], Path("gt.xlsx"), Path("imgs"))
    assert command[1].endswith("run_benchmark.py")
    assert command[command.index("--model") + 1] == "gemini"
    assert command[command.index("--ground-truth") + 1] == "gt.xlsx"
    assert command[command.index("--images") + 1] == "imgs"
    assert command[command.index("--pages") + 1 :] == ["p2", "p4"]


def test_a_card_both_arms_failed_is_reported_not_dropped(tmp_path):
    """The hole an explicit card list closes: with neither arm holding a raw
    file, a union over the directories would omit the card entirely and the run
    would look complete."""
    _write(tmp_path, "a", "p1", {"Municipality": "56"})
    _write(tmp_path, "b", "p1", {"Municipality": "56"})

    union = {r["page_id"] for r in pair_cards("a", "b", tmp_path, FIELDS)}
    assert union == {"p1"}  # p9 is invisible without a card list

    listed = {
        r["page_id"]: r
        for r in pair_cards("a", "b", tmp_path, FIELDS, page_ids=["p1", "p9"])
    }
    assert set(listed) == {"p1", "p9"}
    assert listed["p9"]["counts"] == {NO_SECOND_OPINION: len(FIELDS)}


# --- self-reported confidence bands (step 5) --------------------------------


BANDED = json.dumps(
    {
        "Municipality": {"value": "56", "confidence": "high"},
        "Weekly Rent": {"value": "04", "confidence": "low"},
        "Garden": {"value": None, "confidence": "high"},
    }
)


def test_banded_output_still_yields_plain_values(tmp_path):
    """A banded raw file has to read back like any other, or --rescore, scoring
    and every existing extractor path break on it."""
    _write(tmp_path, "a", "p1", BANDED)
    fields, _ = load_arm(tmp_path, "a")
    assert fields["p1"]["Municipality"] == "56"
    assert fields["p1"]["Weekly Rent"] == "04"  # leading zero survives the unwrap
    assert fields["p1"]["Garden"] == ""


def test_bands_reach_the_paired_output(tmp_path):
    _write(tmp_path, "a", "p1", BANDED)
    _write(tmp_path, "b", "p1", {"Municipality": "56", "Weekly Rent": "04"})
    record = pair_cards("a", "b", tmp_path, FIELDS)[0]
    assert record["fields"]["Municipality"]["a_band"] == "high"
    assert record["fields"]["Weekly Rent"]["a_band"] == "low"
    # arm B was never asked for a band, so it reports none rather than a default
    assert "b_band" not in record["fields"]["Municipality"]


def test_an_unasked_model_has_no_bands_not_low_ones(tmp_path):
    """Absent and "low" are different claims: never asked, versus asked and
    could not read it. Defaulting one to the other would route the whole
    unbanded corpus into review."""
    _write(tmp_path, "a", "p1", {"Municipality": "56"})
    _, bands = load_arm(tmp_path, "a")
    assert bands["p1"] == {}
    record = pair_cards("a", "a", tmp_path, FIELDS)[0]
    assert "a_band" not in record["fields"]["Municipality"]


# --- regressions from the IT-98 review --------------------------------------


def test_an_empty_raw_file_is_not_a_saved_reading(tmp_path):
    """The card-stranding bug. run_benchmark used to write a zero-byte file for
    a batch slot the model skipped; missing_pages tested existence, so that card
    was never re-requested and paired as no_second_opinion forever."""
    raw = tmp_path / "a" / "raw"
    raw.mkdir(parents=True)
    (raw / "p1.txt").write_text("")
    (raw / "p2.txt").write_text(json.dumps({"Municipality": "56"}))

    assert missing_pages(tmp_path, "a", ["p1", "p2"]) == ["p1"]
    fields, _ = load_arm(tmp_path, "a")
    assert "p1" not in fields  # no answer at all, not an unusable one
    assert set(fields) == {"p2"}


def test_fetch_command_forwards_the_results_root():
    """Without this the subprocess extracts into the default root while the
    pairing reads a custom one, so every card reports no_second_opinion and each
    re-run re-buys all 30 against a 20/day cap."""
    command = fetch_command(
        "gemini", ["p1"], Path("gt.xlsx"), Path("imgs"), Path("/tmp/elsewhere")
    )
    assert command[command.index("--results-root") + 1] == "/tmp/elsewhere"


def test_classify_never_disagrees_with_the_scorer():
    """One definition of "the same value". Two would let a pair count as
    agreeing here while scoring as a mismatch there, which is the bug sharing
    scoring.normalise exists to prevent."""
    from ground_truth import BenchmarkCard
    from scoring import score_structured

    pairs = [("04", "4"), ("1", "1."), ("0", "O"), ("-", "B"), ("3", "8"), ("56", "56")]
    card = BenchmarkCard(
        page_id="x",
        source_page=1,
        image_path=None,
        fields={f"f{i}": want for i, (want, _) in enumerate(pairs)},
    )
    score = score_structured(card, {f"f{i}": got for i, (_, got) in enumerate(pairs)})
    scored_equal = {f"f{i}" for i in range(len(pairs))} - {
        m[0] for m in score.mismatches
    }
    classified_equal = {
        f"f{i}"
        for i, (a, b) in enumerate(pairs)
        if classify(a, b) in (AGREE, BOTH_BLANK)
    }
    assert scored_equal == classified_equal


# --- confidence reaches the output (IT-99) ----------------------------------


def test_paired_records_carry_a_confidence_score(tmp_path):
    """IT-99 AC1: a run that writes fields without scores is the failure this
    guards. The paired JSON is what IT-100 and IT-85 both read."""
    _write(tmp_path, "a", "p1", {"Municipality": "56"})
    _write(tmp_path, "b", "p1", {"Municipality": "56"})
    record = pair_cards("a", "b", tmp_path, FIELDS)[0]

    assert record["scored"]["Municipality"]["source_agreement"] == AGREE
    assert 0.0 <= record["scored"]["Municipality"]["confidence"] <= 1.0


def test_a_stranded_card_is_scored_low_not_skipped(tmp_path):
    """A card only one arm reached still gets a number -- AC1 admits no
    exemption, and skipping it would hide the half-failed run."""
    from survey.confidence.field import CONFIDENCE_BY_CLASS

    _write(tmp_path, "a", "p1", {"Municipality": "56"})
    records = {r["page_id"]: r for r in pair_cards("a", "b", tmp_path, FIELDS)}
    scored = records["p1"]["scored"]["Municipality"]

    assert scored["source_agreement"] == NO_SECOND_OPINION
    assert scored["confidence"] < CONFIDENCE_BY_CLASS[AGREE]


def test_summarise_reports_the_confidence_distribution(tmp_path):
    """AC5 of IT-100 needs a distribution, not a headline number."""
    from survey.confidence.field import CONFIDENCE_BY_CLASS

    _write(tmp_path, "a", "p1", {"Municipality": "56", "Weekly Rent": "04"})
    _write(tmp_path, "b", "p1", {"Municipality": "56", "Weekly Rent": "4"})
    text = summarise(pair_cards("a", "b", tmp_path, FIELDS))

    assert "confidence" in text.lower()
    assert f"{CONFIDENCE_BY_CLASS[AGREE]:.2f}" in text
    assert f"{CONFIDENCE_BY_CLASS[DISAGREE]:.2f}" in text


# --- the card-level score reaches the output (IT-85) ------------------------


def test_every_paired_record_carries_a_card_score(tmp_path):
    """IT-85 AC1, including the card only one arm read."""
    _write(tmp_path, "a", "p1", {"Municipality": "56"})
    _write(tmp_path, "b", "p1", {"Municipality": "56"})
    _write(tmp_path, "a", "p2", {"Municipality": "56"})  # b never answered

    records = pair_cards("a", "b", tmp_path, FIELDS)

    assert len(records) == 2
    for record in records:
        score = record["card_confidence"]
        assert isinstance(score, float), f"{record['page_id']}: {score!r}"
        assert 0.0 <= score <= 1.0, f"{record['page_id']}: {score}"


def test_the_card_score_comes_from_its_own_fields(tmp_path):
    """Presence alone would pass on a constant. A corroborated card scores at
    the agree constant, a stranded one below it."""
    from survey.confidence.field import CONFIDENCE_BY_CLASS

    _write(tmp_path, "a", "p1", {name: "56" for name in FIELDS})
    _write(tmp_path, "b", "p1", {name: "56" for name in FIELDS})
    _write(tmp_path, "a", "p2", {name: "56" for name in FIELDS})

    records = {r["page_id"]: r for r in pair_cards("a", "b", tmp_path, FIELDS)}

    assert records["p1"]["card_confidence"] == CONFIDENCE_BY_CLASS[AGREE]
    assert records["p2"]["card_confidence"] < records["p1"]["card_confidence"]


def test_a_bad_card_score_fails_the_run(tmp_path, monkeypatch):
    """AC1 asks the assertion to fail the run, so prove it does -- an
    assertion nothing calls passes every test there is."""
    monkeypatch.setattr("dual_extract.card_confidence", lambda scores: 2.0)
    _write(tmp_path, "a", "p1", {"Municipality": "56"})
    _write(tmp_path, "b", "p1", {"Municipality": "56"})

    with pytest.raises(AssertionError):
        pair_cards("a", "b", tmp_path, FIELDS)


def test_omissions_are_not_explicit_blanks():
    paired = compare_fields({"Garden": None}, {}, FIELDS)
    assert paired["Garden"]["a_state"] == "blank"
    assert paired["Garden"]["b_state"] == "omitted"
    assert paired["Garden"]["agreement"] == NO_SECOND_OPINION
    assert paired["Weekly Rent"]["agreement"] == NO_SECOND_OPINION


def test_failed_and_absent_arms_remain_distinct():
    paired = compare_fields(None, None, FIELDS, first_state="failed")
    assert paired["Garden"]["a_state"] == "failed"
    assert paired["Garden"]["b_state"] == "absent"
    assert paired["Garden"]["a_available"] is False

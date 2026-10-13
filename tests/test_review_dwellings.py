"""Dwelling queue summaries and bounded, physical-card review context."""

from copy import deepcopy
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient
from review_support import decide, refs, setup_review

from survey.records import Reference, ReviewError, card_index
from survey.review.api import create_app
from survey.review.service import ReviewService


def test_summary_is_lightweight_and_preserves_flags_scope(tmp_path, monkeypatch):
    service, _ = setup_review(tmp_path)
    monkeypatch.setattr(
        service,
        "item",
        lambda *_args, **_kwargs: pytest.fail("Summary expanded an item"),
    )
    monkeypatch.setattr(
        service.scans, "get_scan", lambda *_args: pytest.fail("Summary rendered a scan")
    )
    queue = service.dwellings("demo")
    assert len(queue["dwellings"]) == 1
    row = queue["dwellings"][0]
    assert row["record_id"] == "27-0006-01"
    assert row["address"] == "Synthetic address only"
    assert row["card_count"] == 2
    assert (row["total"], row["resolved"], row["unresolved"]) == (5, 0, 5)
    assert row["next_item_id"] == refs()[0].item_id
    assert row["score"] is None
    assert row["status"] == "pending"
    assert "items" not in queue and "field" not in row
    assert queue["summary"]["unscored_cards"] == 2
    assert queue["summary"]["average_card_score"] is None
    assert service.dwellings("missing")["dwellings"] == []


def test_independent_physical_records_do_not_group_by_display_id(tmp_path):
    service, _ = setup_review(tmp_path)
    records, version = service.store.regions["demo"]
    other = deepcopy(records[0])
    for household in other["dwelling"]["households"]:
        for card in household["cards"]:
            card["page"] += 10
    # Future nullable display IDs are irrelevant to physical membership.
    other["dwelling"]["households"][0]["record_id"] = None
    records.append(other)
    service.store.cards["demo"] = card_index(records)
    extra = replace(refs()[0], page=11)
    service.replace_queue([extra, *refs()], [])
    rows = service.dwellings("demo")["dwellings"]
    assert len(rows) == 2
    assert rows[0]["record_id"] is None
    assert rows[0]["first_item_id"] == extra.item_id
    assert rows[0]["id"] != rows[1]["id"]
    identities = [row["id"] for row in rows]
    records.reverse()
    service.store.cards["demo"] = card_index(records)
    service.reindex_history()
    assert [row["id"] for row in service.dwellings("demo")["dwellings"]] == identities
    assert service.store.regions["demo"][1] == version


def test_scores_use_actual_cards_and_leave_unknown_dwelling_score(tmp_path):
    service, _ = setup_review(tmp_path)
    record = service.store.regions["demo"][0][0]
    record["dwelling"]["households"][0]["cards"][0]["confidence"] = 0.91
    record["dwelling"]["households"][1]["cards"][0]["confidence"] = 0.75
    queue = service.dwellings("demo")
    assert queue["dwellings"][0]["score"] == 0.75
    assert queue["summary"]["average_card_score"] == pytest.approx(0.83)
    assert queue["summary"]["scored_cards"] == 2
    # Counts are from all actual cards, including households with no flagged field.
    service.replace_queue([refs()[0]], [])
    assert service.dwellings("demo")["summary"]["scored_cards"] == 2
    record["dwelling"]["households"][1]["cards"][0]["confidence"] = None
    queue = service.dwellings("demo")
    assert queue["dwellings"][0]["score"] is None
    assert queue["summary"]["average_card_score"] == 0.91
    assert queue["summary"]["unscored_cards"] == 1


def test_summary_progress_last_reviewer_undo_and_restart(tmp_path):
    service, settings = setup_review(tmp_path)
    identity = service.dwellings("demo")["dwellings"][0]["id"]
    saved = decide(service)
    row = service.dwellings("demo")["dwellings"][0]
    assert row["resolved"] == 1 and row["status"] == "in_progress"
    assert row["last_reviewer"] == "Test Reviewer"
    assert row["last_reviewed_at"] == saved["decision"]["timestamp"]
    restarted = ReviewService(
        service.store.__class__(settings.data_checkout / "results"),
        refs(),
        [],
        service.scans,
    )
    assert restarted.dwellings("demo")["dwellings"][0]["resolved"] == 1
    undone = restarted.apply_decision(
        refs()[1].item_id,
        "undo",
        "Second reviewer",
        restarted.item(refs()[1].item_id)["version"],
        "undo",
        undo_target=saved["decision"]["id"],
    )
    row = restarted.dwellings("demo")["dwellings"][0]
    assert row["id"] == identity
    assert row["resolved"] == 0 and row["status"] == "pending"
    assert row["last_reviewer"] == "Second reviewer"
    assert undone["item"]["review_state"] == "pending"


def test_completed_dwelling_is_reopenable_but_diagnostic_blocks_completion(tmp_path):
    service, _ = setup_review(tmp_path)
    service.replace_queue([refs()[0]], [])
    decide(service, refs()[0], action="accept")
    queue = service.dwellings("demo")
    row = queue["dwellings"][0]
    assert row["status"] == "complete"
    assert row["next_item_id"] is None
    assert row["first_item_id"] == refs()[0].item_id
    assert queue["complete"] and queue["summary"]["completed_dwellings"] == 1
    unsupported = Reference("demo", "synthetic.pdf", 1, "/dwelling/address")
    service.replace_queue([refs()[0], unsupported], [])
    queue = service.dwellings("demo")
    assert not queue["complete"]
    assert queue["total"] == 2 and queue["unresolved"] == 1
    assert queue["dwellings"][0]["status"] == "blocked"
    assert service.dwelling_items(row["id"], "demo")["diagnostics"]


def test_selected_dwelling_printed_order_and_readonly_card_context(tmp_path):
    service, _ = setup_review(tmp_path)
    identity = service.dwellings("demo")["dwellings"][0]["id"]
    queue = service.dwelling_items(identity, "demo")
    assert len(queue["items"]) == 5
    assert [item["label"] for item in queue["items"]] == [
        "Municipality",
        "Weekly Rent",
        "Occupation of H.",
        "Garden",
        "Weekly Rent",
    ]
    assert all("card_fields" not in item for item in queue["items"])
    first = service.item(refs()[0].item_id)
    assert first["dwelling_id"] == identity
    assert first["field_kind"] == "numeric_sentinel"
    assert first["code_list"]
    context = {field["label"]: field for field in first["card_fields"]}
    assert context["Garden"]["id"] == refs()[2].item_id
    assert context["Age of Head"]["id"] is None
    assert all("review" not in field["field"] for field in context.values())
    second = service.item(refs()[1].item_id)
    assert "Garden" not in {field["label"] for field in second["card_fields"]}
    assert len(second["cards"]) == 2
    assert [card["household_no"] for card in second["cards"]] == ["1", "2"]
    with pytest.raises(ReviewError, match="supplied flagged set"):
        service.dwelling_items(identity, "other")


def test_metadata_bom_titles_and_http_routes(tmp_path):
    service, settings = setup_review(tmp_path, with_git=True)
    (settings.scan_root / "metadata.csv").write_text(
        'Node ID,Node Title\ndemo,"Demo, part 1"\n', encoding="utf-8-sig"
    )
    with TestClient(create_app(settings), base_url="http://127.0.0.1:8765") as client:
        queue = client.get("/api/dwellings?region=demo").json()
        assert queue["region_title"] == "Demo, part 1"
        assert queue["summary"]["dwellings"] == 1
        identity = queue["dwellings"][0]["id"]
        response = client.get(f"/api/dwellings/{identity}/items?region=demo")
        assert response.status_code == 200 and len(response.json()["items"]) == 5
        assert (
            client.get(f"/api/dwellings/{identity}/items?region=wrong").status_code
            == 404
        )
        assert (
            client.get("/api/dwellings/not-a-dwelling/items?region=demo").status_code
            == 404
        )
        item = client.get(f"/api/review-items/{refs()[0].item_id}").json()
        assert item["region_title"] == queue["region_title"]
    assert service.region_titles == {}


@pytest.mark.parametrize("index", [0, 1])
def test_household_municipality_flags_have_actionable_card_context(tmp_path, index):
    service, _ = setup_review(tmp_path)
    ref = Reference(
        "demo",
        "synthetic.pdf",
        index + 1,
        f"/dwelling/households/{index}/municipality",
    )
    service.replace_queue([*refs(), ref], [])
    item = service.item(ref.item_id)
    field = next(field for field in item["card_fields"] if field["id"] == ref.item_id)
    assert field["field_path"] == ref.field_path
    assert field["label"] == "Municipality"
    assert item["allowed_actions"] == ["accept"]
    saved = decide(service, ref, action="accept")
    assert saved["item"]["resolved"]
    assert any(
        field["id"] == ref.item_id and field["review_state"] != "pending"
        for field in saved["item"]["card_fields"]
    )
    # The first card's shared alias remains actionable when separately flagged.
    if index == 0:
        assert any(field["id"] == refs()[3].item_id for field in item["card_fields"])


def test_region_averages_do_not_weight_by_number_of_flags(tmp_path):
    service, _ = setup_review(tmp_path)
    record = service.store.regions["demo"][0][0]
    for household in record["dwelling"]["households"]:
        household["cards"][0]["confidence"] = 0.91
    other = deepcopy(record)
    other["region"] = "other"
    for household in other["dwelling"]["households"]:
        household["cards"][0]["confidence"] = 0.0
    service.store.regions["other"] = ([other], "synthetic-version")
    service.store.cards["other"] = card_index([other])
    service.replace_queue([*refs(), replace(refs()[0], region="other")], [])
    queue = service.dwellings("demo")
    assert queue["summary"]["average_card_score"] == 0.91
    assert queue["summary"]["dwellings"] == 1
    assert queue["summary"]["queued_dwellings"] == 1
    assert queue["all_regions"]["average_card_score"] == pytest.approx(0.455)
    assert queue["all_regions"]["scored_cards"] == 4
    assert queue["all_regions"]["dwellings"] == 2
    assert queue["all_regions"]["queued_dwellings"] == 2
    assert len(queue["dwellings"]) == 1
    assert service.dwellings("other")["summary"]["average_card_score"] == 0.0


def test_regenerated_flags_keep_last_reviewer_from_removed_decisions(tmp_path):
    service, _ = setup_review(tmp_path)
    decide(service, refs()[0], action="accept")
    service.replace_queue([refs()[1]], [])
    row = service.dwellings("demo")["dwellings"][0]
    assert (row["total"], row["resolved"]) == (1, 0)
    assert row["last_reviewer"] == "Test Reviewer"
    assert row["status"] == "pending"


def test_legacy_notes_are_visible_and_block_summary_completion(tmp_path):
    service, _ = setup_review(tmp_path)
    for index, ref in enumerate(refs()):
        decide(service, ref, action="accept", request_id=f"accept-{index}")
    assert service.dwellings("demo")["complete"]
    record = service.store.regions["demo"][0][0]
    record["dwelling"]["households"][0]["notes"] = {"value": "legacy"}
    service.reindex_history()
    queue = service.dwellings("demo")
    assert queue["dwellings"][0]["status"] == "blocked"
    assert queue["diagnostics"][0]["code"] == "legacy_notes"
    assert not queue["complete"]
    assert queue["summary"]["completed_dwellings"] == 0
    assert queue["total"] == queue["dwellings"][0]["total"] == len(refs())
    assert queue["unresolved"] == len(refs())


def test_reindex_retains_stale_flags_as_diagnostics_and_recovers(tmp_path):
    service, _ = setup_review(tmp_path)
    record = service.store.regions["demo"][0][0]
    original = deepcopy(record["dwelling"]["households"])
    record["dwelling"]["households"].reverse()
    service.store.cards["demo"] = card_index([record])
    service.reindex_history({"demo"})
    queue = service.dwellings("demo")
    assert queue["total"] == 5
    assert queue["unresolved"] == 5
    assert not queue["complete"]
    assert len(queue["diagnostics"]) == 5
    assert all(d["item_id"] and d["page"] for d in queue["diagnostics"])
    assert not queue["dwellings"]
    record["dwelling"]["households"] = original
    service.store.cards["demo"] = card_index([record])
    service.reindex_history({"demo"})
    repaired = service.dwellings("demo")
    assert repaired["total"] == 5
    assert repaired["diagnostics"] == []
    assert len(repaired["dwellings"]) == 1


def test_other_region_query_refreshes_global_scan_completion(tmp_path):
    service, settings = setup_review(tmp_path)
    service.replace_queue([refs()[0]], [])
    decide(service, refs()[0], action="accept")
    assert service.dwellings("demo")["all_regions"]["completed_dwellings"] == 1
    (settings.scan_root / "demo" / "synthetic.pdf").unlink()
    other = service.dwellings("other")
    assert other["all_regions"]["completed_dwellings"] == 0
    queue = service.dwellings("demo")
    assert queue["total"] == 1 and queue["resolved"] == 0
    assert queue["unresolved"] == 1 and not queue["complete"]
    assert queue["diagnostics"][0]["code"] == "missing_scan"
    assert queue["dwellings"][0]["status"] == "blocked"


def test_incomplete_optional_metadata_does_not_block_review(tmp_path):
    service, settings = setup_review(tmp_path)
    (settings.scan_root / "metadata.csv").write_text(
        "Node ID,Node Title\ndemo\n", encoding="utf-8"
    )
    restarted = ReviewService(service.store, refs(), [], service.scans)
    assert restarted.dwellings("demo")["region_title"] is None
    assert restarted.item(refs()[0].item_id)["region_title"] is None


def test_decision_and_undo_return_current_card_navigation(tmp_path):
    service, _ = setup_review(tmp_path)
    service.replace_queue([refs()[0], refs()[2]], [])
    saved = decide(service, refs()[0], action="accept")
    card = saved["item"]["cards"][0]
    assert card["next_item_id"] == refs()[2].item_id
    assert card == service.item(refs()[0].item_id)["cards"][0]
    completed = decide(
        service, refs()[2], action="accept", request_id="second-navigation"
    )
    assert completed["item"]["cards"][0]["next_item_id"] is None
    undone = service.apply_decision(
        refs()[2].item_id,
        "undo",
        "Undo reviewer",
        completed["item"]["version"],
        "undo-navigation",
        undo_target=completed["decision"]["id"],
    )
    assert undone["item"]["cards"][0]["next_item_id"] == refs()[2].item_id
    assert undone["item"]["cards"] == service.item(refs()[2].item_id)["cards"]


def test_locator_and_unqueued_household_context_do_not_create_actions(tmp_path):
    service, _ = setup_review(tmp_path)
    service.replace_queue([refs()[0]], [])
    item = service.item(refs()[0].item_id)
    assert item["column"] == "Middle column"
    assert item["household_count"] == 2
    assert len(item["cards"]) == 2
    assert item["cards"][1]["first_item_id"] is None
    assert item["cards"][1]["next_item_id"] is None
    assert item["cards"][1]["score"] is None
    fields = {field["label"]: field for field in item["card_fields"]}
    assert fields["Municipality"]["column"] == "Left column"
    assert fields["Length of Residence"]["column"] == "Right column"
    assert fields["Weekly Rent"]["column"] == "Middle column"
    assert service.dwelling_items(item["dwelling_id"], "demo")["total"] == 1


@pytest.mark.parametrize("page", [None, "absent"])
def test_unqueued_card_without_page_cannot_block_supported_field(tmp_path, page):
    service, _ = setup_review(tmp_path)
    service.replace_queue([refs()[0]], [])
    card = service.store.regions["demo"][0][0]["dwelling"]["households"][1]["cards"][0]
    if page == "absent":
        card.pop("page")
    else:
        card["page"] = page
    item = service.item(refs()[0].item_id)
    assert item["source"]["page"] == 1
    assert item["cards"][1]["page"] is None
    assert item["cards"][1]["first_item_id"] is None
    assert "accept" in item["allowed_actions"]

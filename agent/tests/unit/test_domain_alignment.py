"""Helpers that keep the agent in line with what the real Domain Service accepts and returns."""

from datetime import date, timedelta

from agent.app.contracts.enums import CAUSE_CATEGORIES
from agent.app.contracts.models import DailyRate, ToolResult, Window
from agent.app.domain.catalog import load_bundled_catalog
from agent.app.graph.nodes.common import DETAILS_NOTE_LIMIT, compact_details, normalize_result
from agent.app.graph.nodes.load_case import clip_window


def daily(first: str, last: str) -> list[DailyRate]:
    start, end = date.fromisoformat(first), date.fromisoformat(last)
    return [DailyRate(date=(start + timedelta(days=n)).isoformat()) for n in range((end - start).days + 1)]


# --- The 42-day window stays inside the store's data -----------------------------------------------


def test_the_window_is_the_42_days_ending_on_the_case_end():
    assert clip_window(date(2026, 11, 15), daily("2026-10-05", "2026-11-15")) == (date(2026, 10, 5), date(2026, 11, 15))


def test_the_window_never_starts_before_the_data():
    # A monitor run with as_of Nov 10: 41 days earlier is Sep 30, before the seed's first day.
    assert clip_window(date(2026, 11, 10), daily("2026-10-05", "2026-11-10")) == (date(2026, 10, 5), date(2026, 11, 10))


def test_the_window_never_ends_after_the_data():
    assert clip_window(date(2026, 11, 16), daily("2026-10-06", "2026-11-15")) == (date(2026, 10, 6), date(2026, 11, 15))


def test_without_daily_rates_the_window_is_42_days():
    assert clip_window(date(2026, 11, 15), []) == (date(2026, 10, 5), date(2026, 11, 15))


# --- Domain's 422 details become a short note --------------------------------------------------------


def test_details_name_what_domain_rejected():
    assert compact_details({"unknown_modifiers": ["Truffle oil"]}) == "unknown_modifiers: Truffle oil"
    assert compact_details({"data_start": "2026-10-05", "data_end": "2026-11-15"}) == "data runs 2026-10-05 to 2026-11-15"
    errors = {"errors": [{"loc": ["body", "filter", "limit"], "msg": "Input should be less than or equal to 10"}]}
    assert compact_details(errors) == "filter.limit: Input should be less than or equal to 10"
    assert compact_details({}) == ""


def test_details_are_capped():
    many = {"unknown_item_ids": [f"ITEM-X-{n:03d}" for n in range(100)]}
    assert len(compact_details(many)) == DETAILS_NOTE_LIMIT


# --- Record tools always have enough data -------------------------------------------------------------


def test_record_tools_always_have_enough_data():
    thin = ToolResult(tool="event_log", store_id="STORE-I", window=Window(start="2026-11-09", end="2026-11-15"),
                      data_sufficient=False)
    assert normalize_result("event_log", thin).data_sufficient is True
    assert normalize_result("sample_evidence", thin.model_copy(update={"tool": "sample_evidence"})).data_sufficient
    rates = thin.model_copy(update={"tool": "claim_breakdown"})
    assert normalize_result("claim_breakdown", rates).data_sufficient is False


# --- The bundled catalog ------------------------------------------------------------------------------


def test_the_bundled_catalog_has_the_agreed_ids_and_a_handoff_for_every_cause():
    catalog = load_bundled_catalog()
    ids = [entry.action_id for entry in catalog]
    assert len(ids) == len(set(ids))
    assert {"fix_modifier_mapping", "large_order_bag_check", "analyst_review"} <= set(ids)
    handoff = next(entry for entry in catalog if entry.action_id == "analyst_review")
    assert handoff.kind == "handoff" and set(handoff.applies_to) == set(CAUSE_CATEGORIES)


def test_bundled_catalog_copies_are_independent():
    first = load_bundled_catalog()
    first[0].title = "changed"
    assert load_bundled_catalog()[0].title != "changed"

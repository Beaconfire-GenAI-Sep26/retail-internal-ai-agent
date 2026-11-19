import json

import pytest

from agent.app.contracts.models import ActionContent, ProposalCreate, Target, ToolResult
from agent.app.domain.client import DomainError
from agent.app.domain.fixtures import FixtureDomainClient
from agent.tests.conftest import FIXTURES


@pytest.fixture
def client():
    return FixtureDomainClient(FIXTURES)


async def test_breakdown_matches_on_tool_group_and_filter(client):
    r = await client.claim_breakdown("STORE-A", {"filter": {"start": "2026-10-05", "end": "2026-11-15"},
                                                 "group_by": "modifier"})
    assert r.data_sufficient and r.headline.startswith("modifier=Extra sauce")
    assert client.misses == []


async def test_closest_window_wins_and_differences_are_noted(client):
    r = await client.claim_breakdown("STORE-A", {"filter": {"start": "2026-10-31", "end": "2026-11-15"},
                                                 "group_by": "modifier"})
    assert r.window.start == "2026-10-30"
    assert any("Fixture data covers 2026-10-30" in n for n in r.notes)


async def test_unmatched_query_is_an_insufficient_miss(client):
    r = await client.claim_breakdown("STORE-A", {"filter": {"start": "2026-10-05", "end": "2026-11-15",
                                                            "weekday": [2]}, "group_by": "daypart"})
    assert not r.data_sufficient
    assert r.headline == "No fixture matches this query."
    assert len(client.misses) == 1


async def test_event_log_filters_by_local_date_and_type(client):
    r = await client.event_log("STORE-A", "2026-10-25", "2026-10-31", [])
    assert r.evidence_ids == ["EV-EVT-000005", "EV-EVT-000006"]
    r = await client.event_log("STORE-A", "2026-10-05", "2026-11-15", ["store_downtime"])
    assert r.evidence_ids == ["EV-EVT-000003"]


async def test_sample_applies_the_limit(client):
    r = await client.evidence_sample("STORE-A", {"evidence_type": "claim", "limit": 3,
                                                 "filter": {"start": "2026-10-30", "end": "2026-11-15",
                                                            "modifiers": ["Extra sauce"]}})
    assert len(r.evidence) == 3 and r.evidence_ids == [e.evidence_id for e in r.evidence]


async def test_unknown_case_is_not_found(client):
    with pytest.raises(DomainError) as info:
        await client.get_case("CASE-9999")
    assert info.value.status == 404


async def test_resolve_marks_unknown_ids_invalid(client):
    known = client.stores["STORE-A"].overview.evidence_ids[0]
    r = await client.resolve_evidence("STORE-A", [known, "EV-CLM-999999"])
    assert r.valid == [known]
    assert r.invalid == [{"evidence_id": "EV-CLM-999999", "reason": "not_found"}]


async def test_second_pending_proposal_conflicts(client):
    body = ProposalCreate(investigation_id="INV-1", kind="handoff", evidence_ids=[],
                          content=ActionContent(action_id="fix_modifier_mapping", owner_team="pos_team", title="t",
                                                instructions="i", rationale="r", recheck_after_days=14,
                                                target=Target(item_id=[], modifiers=["Extra sauce"], daypart=[],
                                                              item_count_min=None)))
    first = await client.create_proposal("CASE-0001", body)
    assert first.proposal_id == "PROP-0001"
    with pytest.raises(DomainError) as info:
        await client.create_proposal("CASE-0001", body)
    assert info.value.code == "PROPOSAL_PENDING"
    case = await client.get_case("CASE-0001")
    assert [p.proposal_id for p in case.proposals] == ["PROP-0001"]


def test_every_fixture_result_follows_the_contract_shape():
    for path in FIXTURES.glob("*/*.json"):
        data = json.loads(path.read_text(encoding="utf-8"))
        if path.name in ("overview.json", "fraud_signals.json", "fraud_signals_flagged.json"):
            ToolResult.model_validate(data)
        if path.name == "checks.json":
            for entry in data:
                ToolResult.model_validate(entry["result"])
                flt = entry["match"].get("filter", {})
                for key, value in flt.items():
                    if isinstance(value, list):
                        assert value == sorted(value) or key in ("daypart", "error_category"), (path, key)
                assert "start" not in flt and "end" not in flt


def test_menu_modifiers_cover_the_scenarios(client):
    mods = {m for item in client.stores["STORE-A"].menu for m in item.available_modifiers}
    assert "Extra sauce" in mods

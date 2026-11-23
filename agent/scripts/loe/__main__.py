"""The LOE benchmark (B-05): works one case with the fixed playbook, through Domain, and prints one JSON line.

It runs inside the agent container, where Domain's internal routes are reachable:

    docker compose exec -T agent /app/.venv/bin/python -m agent.scripts.loe < request.json

The request is {"token", "case_id", "investigation_id"}, read from stdin so the token never reaches the command line or
a file. The benchmark has the agent's data and permissions: its questions and recommendations are proposals that Domain
checks, and only an analyst can approve them. It calls no model.

The first call either files the playbook's question ("awaiting_approval") or concludes. After the analyst approves the
question and the merchant replies, or the analyst records no_reply, a second call with the same investigation ID
concludes.
"""

from __future__ import annotations

import asyncio
import json
import sys
from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo

from agent.app.config import get_settings
from agent.app.contracts.models import (
    ActionCatalogEntry,
    ActionContent,
    CaseDetail,
    MenuItem,
    MerchantQuestionContent,
    ProposalCreate,
)
from agent.app.domain.client import DomainError, HttpDomainClient
from agent.app.graph.finalize import describe_target
from agent.app.graph.nodes.common import domain_error, window_end_date
from agent.scripts.loe.playbook import work_case
from agent.scripts.loe.tools import Case, Conclusion, Day, Question, Reply, Tools


def case_facts(detail: CaseDetail, menu: list[MenuItem]) -> Case:
    daily = tuple(Day(date.fromisoformat(d.date[:10]), d.rate, d.claims, d.eligible_orders) for d in detail.daily_rates)
    end = min(window_end_date(detail.window_end, detail.store.timezone), daily[-1].date)
    opened = datetime.fromisoformat(detail.window_start.replace("Z", "+00:00"))
    return Case(
        case_id=detail.case_id, store_id=detail.store_id, trigger_rule=detail.trigger_rule,
        start=max(opened.astimezone(ZoneInfo(detail.store.timezone)).date(), daily[0].date), end=end,
        data_start=daily[0].date, data_end=daily[-1].date, rate=detail.mi_rate or 0.0, baseline=detail.baseline_rate,
        goal=detail.goal_rate or 0.05, claims=detail.attributable_claims or 0, orders=detail.eligible_orders or 0,
        daily=daily, menu=tuple(menu))


def question_proposal(investigation_id: str, question: Question) -> ProposalCreate:
    return ProposalCreate(
        investigation_id=investigation_id, kind="merchant_question",
        content=MerchantQuestionContent(question_text=question.text, why_asked=question.why),
        evidence_ids=list(dict.fromkeys(question.evidence_ids))[:20])


def recommendation(conclusion: Conclusion, catalog: list[ActionCatalogEntry]) -> dict[str, Any] | None:
    entry = next((e for e in catalog if e.action_id == conclusion.action_id), None)
    if conclusion.cause is None or entry is None:
        return None
    target = {"item_id": [], "modifiers": [], "daypart": [], "item_count_min": None, **conclusion.target}
    return {"kind": entry.kind, "action_id": entry.action_id, "owner_team": entry.owner_team,
            "rationale": conclusion.summary, "target": target, "recheck_after_days": entry.default_recheck_days}


def action_proposal(investigation_id: str, rec: dict[str, Any], conclusion: Conclusion,
                    catalog: list[ActionCatalogEntry], menu: list[MenuItem]) -> ProposalCreate:
    title = next(e.title for e in catalog if e.action_id == rec["action_id"])
    scope = describe_target(rec["target"], [m.model_dump(mode="json") for m in menu])
    content = ActionContent(
        action_id=rec["action_id"], owner_team=rec["owner_team"], title=title, rationale=rec["rationale"],
        instructions=f"{title}. Scope: {scope}. A recheck runs {rec['recheck_after_days']} days after dispatch.",
        target=rec["target"], recheck_after_days=rec["recheck_after_days"])
    return ProposalCreate(investigation_id=investigation_id, kind=rec["kind"], content=content,
                          evidence_ids=conclusion.supporting)


async def work(request: dict[str, str], domain: Any, checks: list[dict[str, Any]]) -> dict[str, Any]:
    case_id, investigation_id = request["case_id"], request["investigation_id"]
    detail = await domain.get_case(case_id)  # also scopes every later call to this case and store
    menu = await domain.get_menu(detail.store_id)
    asked = [p for p in detail.proposals if p.investigation_id == investigation_id and p.kind == "merchant_question"]
    reply = None
    if asked:
        replies = await domain.list_merchant_replies(case_id)
        found = next((r for r in replies if r.proposal_id == asked[0].proposal_id), None)
        if found is None:
            return {"status": "awaiting_merchant", "pending_proposal_id": asked[0].proposal_id}
        reply = Reply(found.evidence_id, found.outcome, found.text)

    case = case_facts(detail, menu)
    step = await work_case(Tools(domain, case, checks), case, reply)
    if isinstance(step, Question):
        if reply is not None:
            raise RuntimeError("the playbook asked a second question")
        proposal = await domain.create_proposal(case_id, question_proposal(investigation_id, step))
        return {"status": "awaiting_approval", "pending_proposal_id": proposal.proposal_id, "checks": checks,
                "question": step.text}

    catalog = await domain.get_catalog()
    rec = recommendation(step, catalog)
    result = {
        "outcome": "diagnosis" if step.cause and rec else "unsure",
        "cause_category": step.cause if rec else None,
        "cause_started_at": step.started_on.isoformat() if rec and step.started_on else None,
        "confidence": step.confidence, "summary": step.summary,
        "supporting_evidence_ids": step.supporting if rec else [],
        "contradicting_evidence_ids": step.contradicting,
        "ruled_out": [{"cause_category": r.cause, "reason": r.reason, "evidence_ids": r.evidence_ids, "check_ids": []}
                      for r in step.ruled_out],
        "evidence_gaps": step.gaps, "recommendation": rec, "proposal_id": None,
    }
    if rec:
        body = action_proposal(investigation_id, rec, step, catalog, menu)
        result["proposal_id"] = (await domain.create_proposal(case_id, body)).proposal_id
    return {"status": "completed" if rec else "unsure", "checks": checks, "result": result,
            "reply": {"outcome": reply.outcome, "evidence_id": reply.evidence_id} if reply else None}


async def main() -> None:
    request = json.loads(sys.stdin.read())
    settings = get_settings()
    client = HttpDomainClient(settings.domain_service_url, settings.internal_service_token,
                              timeout=settings.domain_timeout_seconds)
    checks: list[dict[str, Any]] = []
    try:
        domain = client.bind(token=request["token"], request_id=f"loe-{request['investigation_id'][-20:]}",
                             investigation_id=request["investigation_id"])
        out = await work(request, domain, checks)
    except DomainError as exc:  # Domain refused a proposal or is down: the run fails, as the agent's would
        out = {"status": "failed", "error": domain_error(exc, "loe"), "checks": checks}
    finally:
        await client.aclose()
    print(json.dumps(out))


if __name__ == "__main__":
    asyncio.run(main())

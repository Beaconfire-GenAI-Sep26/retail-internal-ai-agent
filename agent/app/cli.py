"""Run one investigation from the command line, without the API (the live smoke run).

Run from the repository root:

  uv run --project agent python -m agent.app.cli --store STORE-A
  uv run --project agent python -m agent.app.cli --store STORE-B --effort low --max-steps 10
  uv run --project agent python -m agent.app.cli --store STORE-A --dry-run   # scripted turns, no API key
  uv run --project agent python -m agent.app.cli --case CASE-0001 --domain http --token <jwt> [--dry-run]

With --domain http the agent calls the Domain Service at DOMAIN_SERVICE_URL and forwards --token on
every call, so it sees exactly what that user can see. The token must be an analyst's JWT issued by
Auth; for local work, `python -m domain.scripts.make_demo_token` prints one. The store comes from the
case. Once Domain has its /internal/ routes, an http run also saves a real proposal and reports the
investigation status, even with --dry-run.

Needs ANTHROPIC_API_KEY in agent/.env unless --dry-run. Prints each step as it happens, then the
check sequence, the outcome, fixture misses and cache reads per turn, and saves a JSON report
under scripts/out/.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from shared.security import JWTSettings
from agent.app.auth import verify_token
from agent.app.config import AGENT_ROOT, get_settings
from agent.app.domain.client import DomainError, HttpDomainClient
from agent.app.domain.fixtures import FixtureDomainClient
from agent.app.errors import AppError
from agent.app.graph.build import build_graph, run_config
from agent.app.graph.context import AgentContext
from agent.app.graph.state import initial_state
from agent.app.ids import UlidIdFactory
from agent.app.llm.base import ReasonModel
from agent.app.runner import run_config_record


def _print_update(node: str, update: dict[str, Any]) -> None:
    if node == "reason":
        call = (update.get("model_calls") or [{}])[-1]
        action = (update.get("reason_output") or {}).get("next_action") or {}
        usage = call.get("usage", {})
        detail = action.get("type", "?")
        if detail == "check":
            req = action.get("plan", {}).get("request", {})
            if isinstance(req, str):  # the model sends the request as a JSON string
                try:
                    req = json.loads(req)
                except ValueError:
                    req = {}
            req = req if isinstance(req, dict) else {}
            detail += f" {action.get('plan', {}).get('kind')} {req.get('tool')} {req.get('group_by', '')}".rstrip()
        if update.get("error"):
            detail = f"error {update['error']['code']}: {update['error']['message']}"
        print(f"  reason  turn {update.get('reason_calls')}: {detail} | {call.get('latency_ms', 0)} ms, "
              f"out {usage.get('output_tokens', 0)}, cache read {usage.get('cache_read_input_tokens', 0)}")
    elif node == "guard":
        feedback = update.get("guard_feedback")
        if feedback:
            print(f"  guard   rejected: {', '.join(feedback['rule_ids'])}")
            for v in feedback["violations"][:4]:
                print(f"          {v['rule']}: {v['message'][:160]}")
        elif update.get("end_reason"):
            print(f"  guard   accepted; run ends: {update['end_reason']}")
        else:
            print("  guard   accepted")
    elif node == "run_check":
        if update.get("error"):
            print(f"  check   error {update['error']['code']}: {update['error']['message']}")
            return
        record = update["checks"][-1]
        print(f"  check   {record['kind']} {record['tool']} {record['request'].get('group_by', '')} -> "
              f"{record['result']['headline'][:140]}")
    elif node == "conclude_gate":
        unmet = [c["rule"] for c in (update.get("gate_result") or {}).get("unmet", [])]
        print("  gate    passed" if not unmet else f"  gate    unmet: {', '.join(unmet)}")
    elif node == "finalize":
        result = update.get("result") or {}
        print(f"  final   {result.get('outcome')} {result.get('cause_category') or ''} "
              f"confidence {result.get('confidence')} ({update.get('end_reason')})")
    elif node in ("fail", "load_case") and update.get("error"):
        print(f"  {node}  error {update['error']['code']}: {update['error']['message']}")


def _dry_run_model(store_id: str) -> ReasonModel:
    try:
        from agent.app.llm.scripted_model import ScriptedReasonModel
        from agent.tests.scripts import store_a_turns, store_b_turns
    except ImportError:
        sys.exit("--dry-run needs the tests package next to app/.")
    turns = {"STORE-A": store_a_turns, "STORE-B": store_b_turns}.get(store_id)
    if turns is None:
        sys.exit("--dry-run has scripted turns for STORE-A and STORE-B only.")
    return ScriptedReasonModel(turns())


async def run(args: argparse.Namespace) -> int:
    settings = get_settings()
    overrides: dict[str, Any] = {"agent_domain_mode": args.domain}
    if args.effort:
        overrides["agent_effort"] = args.effort
    if args.speed:
        overrides["agent_speed"] = args.speed
    if args.max_steps:
        overrides["agent_max_steps"] = args.max_steps
    settings = settings.model_copy(update=overrides)

    ids = UlidIdFactory()
    investigation_id = ids.new("INV")
    user_id = "cli"
    if args.domain == "fixtures":
        client: Any = FixtureDomainClient(settings.agent_fixtures_dir)
        if args.case:
            case_id = args.case
            store_id = next(s for s, f in client.stores.items() if f.case.case_id == case_id)
        else:
            store_id = args.store
            case_id = client.case_for_store(store_id).case_id
        domain = client.bind(token="fixtures", request_id="cli", investigation_id=investigation_id)
    else:
        if not (args.case and args.token):
            print("--domain http needs --case and --token (an analyst JWT).")
            return 2
        # Same rule as POST /investigations: only an analyst's own token can start an investigation.
        try:
            principal = verify_token(args.token, settings)
        except AppError as exc:
            print(f"The token was refused: {exc.message}")
            return 2
        if not principal.is_analyst:
            print("--token must be an analyst's JWT (role loe_analyst).")
            return 2
        user_id = principal.user_id
        client = HttpDomainClient(settings.domain_service_url, settings.internal_service_token,
                                  jwt_settings=JWTSettings(settings.jwt_secret, settings.jwt_issuer),
                                  timeout=settings.domain_timeout_seconds, max_retries=settings.agent_max_retries)
        domain = client.bind(token=args.token, request_id="cli", investigation_id=investigation_id)
        try:
            case = await domain.get_case(args.case)
        except DomainError as exc:
            print(f"Domain returned {exc.status} {exc.code} for {args.case}: {exc.message}")
            await client.aclose()
            return 2
        if not principal.can_see(case.store_id):
            print(f"The token has no grant for {case.store_id}.")
            await client.aclose()
            return 2
        case_id, store_id = case.case_id, case.store_id

    if args.dry_run:
        model = _dry_run_model(store_id)
    else:
        if not settings.anthropic_api_key:
            print("ANTHROPIC_API_KEY is empty. Copy agent/.env.example to agent/.env and set it, or use --dry-run.")
            return 2
        from agent.app.llm.anthropic_model import AnthropicReasonModel

        model = AnthropicReasonModel(settings)

    graph = build_graph()
    ctx = AgentContext(domain=domain, model=model, ids=ids, settings=settings, user_id=user_id, request_id="cli",
                       deadline=time.monotonic() + settings.agent_run_timeout_seconds)
    state = initial_state(investigation_id=investigation_id, case_id=case_id, store_id=store_id, started_by=user_id,
                          started_at=datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"), reopen_of=None,
                          run_config=run_config_record(settings, model))
    config = run_config(investigation_id, settings.recursion_limit)
    print(f"{investigation_id}: {store_id} {case_id}, model {model.name}, effort {settings.agent_effort}, "
          f"speed {settings.agent_speed}, max steps {settings.agent_max_steps}")
    started = time.monotonic()
    async for chunk in graph.astream(state, config, context=ctx, stream_mode="updates", durability="sync"):
        for node, update in chunk.items():
            if isinstance(update, dict):
                _print_update(node, update)
    final = dict((await graph.aget_state(config)).values)
    elapsed = time.monotonic() - started

    result = final.get("result") or {}
    print("\nCheck sequence:")
    for c in final.get("checks", []):
        kind = "load_case" if c["source"] == "load_case" else c["kind"]
        print(f"  {c['check_id']} {kind:9} {c['tool']} {c['request'].get('group_by', '')}")
    print("\nHypotheses:")
    for h in final.get("hypotheses", []):
        print(f"  {h['hypothesis_id']} {h['cause_category']:22} {h['status']:12} {h['statement'][:90]}")
    print(f"\nStatus {final.get('status')}, end {final.get('end_reason')}, {final.get('step_count', 0)} checks, "
          f"{final.get('reason_calls', 0)} reason turns, {elapsed:.0f} s")
    if final.get("error"):
        print(f"Error {final['error']['code']}: {final['error']['message']}")
    if result:
        print(f"Outcome {result.get('outcome')} {result.get('cause_category')} confidence {result.get('confidence')}")
        print(f"Summary: {result.get('summary')}")
        for gap in result.get("evidence_gaps", []):
            print(f"  gap: {gap}")
    reads = [c.get("usage", {}).get("cache_read_input_tokens", 0) for c in final.get("model_calls", [])]
    print(f"Cache reads per turn: {reads}")
    print(f"Usage: {final.get('usage', {})}")
    misses = getattr(client, "misses", [])
    print(f"Fixture misses: {len(misses)}")
    for miss in misses:
        print(f"  {miss['tool']} {json.dumps(miss['request'], sort_keys=True)[:160]}")

    out_dir = AGENT_ROOT / "scripts" / "out"
    out_dir.mkdir(parents=True, exist_ok=True)
    path = Path(args.out) if args.out else out_dir / f"smoke-{store_id}-{investigation_id}.json"
    path.write_text(json.dumps({"store_id": store_id, "case_id": case_id, "elapsed_seconds": round(elapsed, 1),
                                "fixture_misses": misses, "state": final}, indent=1, default=str), encoding="utf-8")
    print(f"Report: {path}")
    await client.aclose()
    return 0 if final.get("status") in ("completed", "unsure") else 1


def main() -> None:
    parser = argparse.ArgumentParser(description="Run one investigation without the API.")
    parser.add_argument("--store", default="STORE-A", help="Fixtures mode only; http mode takes it from the case")
    parser.add_argument("--case")
    parser.add_argument("--domain", choices=["fixtures", "http"], default="fixtures")
    parser.add_argument("--token", help="An analyst's JWT, forwarded to Domain, for --domain http")
    parser.add_argument("--effort", choices=["low", "medium", "high", "xhigh", "max"])
    parser.add_argument("--speed", choices=["standard", "fast"])
    parser.add_argument("--max-steps", type=int)
    parser.add_argument("--dry-run", action="store_true", help="Use the scripted test turns instead of Claude")
    parser.add_argument("--out", help="Report path")
    sys.exit(asyncio.run(run(parser.parse_args())))


if __name__ == "__main__":
    main()

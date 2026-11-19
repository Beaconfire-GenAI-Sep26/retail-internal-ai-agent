"""Run one investigation from the command line, without the API (the live smoke run).

  uv run python -m app.cli --store STORE-A
  uv run python -m app.cli --store STORE-B --effort low --max-steps 10
  uv run python -m app.cli --store STORE-A --dry-run      # scripted turns, no API key needed
  uv run python -m app.cli --case CASE-0001 --domain http --token <jwt>

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

from app.config import AGENT_ROOT, get_settings
from app.domain.client import HttpDomainClient
from app.domain.fixtures import FixtureDomainClient
from app.graph.build import build_graph, run_config
from app.graph.context import AgentContext
from app.graph.state import initial_state
from app.ids import UlidIdFactory
from app.llm.base import ReasonModel
from app.runner import run_config_record


def _print_update(node: str, update: dict[str, Any]) -> None:
    if node == "reason":
        call = (update.get("model_calls") or [{}])[-1]
        action = (update.get("reason_output") or {}).get("next_action") or {}
        usage = call.get("usage", {})
        detail = action.get("type", "?")
        if detail == "check":
            req = action.get("plan", {}).get("request", {})
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
        from app.llm.scripted_model import ScriptedReasonModel
        from tests.scripts import store_a_turns, store_b_turns
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

    if args.domain == "fixtures":
        client: Any = FixtureDomainClient(settings.agent_fixtures_dir)
        if args.case:
            case_id = args.case
            store_id = next(s for s, f in client.stores.items() if f.case.case_id == case_id)
        else:
            store_id = args.store
            case_id = client.case_for_store(store_id).case_id
    else:
        if not (args.case and args.token):
            print("--domain http needs --case and --token (an analyst JWT).")
            return 2
        client = HttpDomainClient(settings.domain_service_url, settings.internal_service_token,
                                  timeout=settings.domain_timeout_seconds, max_retries=settings.agent_max_retries)
        case_id, store_id = args.case, args.store or ""

    if args.dry_run:
        model = _dry_run_model(store_id)
    else:
        if not settings.anthropic_api_key:
            print("ANTHROPIC_API_KEY is empty. Copy agent/.env.example to agent/.env and set it, or use --dry-run.")
            return 2
        from app.llm.anthropic_model import AnthropicReasonModel

        model = AnthropicReasonModel(settings)

    ids = UlidIdFactory()
    investigation_id = ids.new("INV")
    domain = client.bind(token=args.token or "fixtures", request_id="cli", investigation_id=investigation_id)
    if args.domain == "http":
        store_id = (await domain.get_case(case_id)).store_id
    graph = build_graph()
    ctx = AgentContext(domain=domain, model=model, ids=ids, settings=settings, user_id="cli", request_id="cli",
                       deadline=time.monotonic() + settings.agent_run_timeout_seconds)
    state = initial_state(investigation_id=investigation_id, case_id=case_id, store_id=store_id, started_by="cli",
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
    parser.add_argument("--store", default="STORE-A")
    parser.add_argument("--case")
    parser.add_argument("--domain", choices=["fixtures", "http"], default="fixtures")
    parser.add_argument("--token", help="Analyst JWT, for --domain http")
    parser.add_argument("--effort", choices=["low", "medium", "high", "xhigh", "max"])
    parser.add_argument("--speed", choices=["standard", "fast"])
    parser.add_argument("--max-steps", type=int)
    parser.add_argument("--dry-run", action="store_true", help="Use the scripted test turns instead of Claude")
    parser.add_argument("--out", help="Report path")
    sys.exit(asyncio.run(run(parser.parse_args())))


if __name__ == "__main__":
    main()

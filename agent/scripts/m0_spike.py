"""M0: the schema and latency spike for the reason call.

  uv run python scripts/m0_spike.py           # offline checks only, no API calls
  uv run python scripts/m0_spike.py --yes     # plus 8 real calls, about $1

The real calls need ANTHROPIC_API_KEY in agent/.env. They send the STORE-A first-turn prompt,
rendered from the fixtures, twice at each of low, medium and high effort and once more pair at
medium with speed="fast". The second call of each pair measures cache reads. The report records
whether the schema compiled, latency, output tokens, cache reads, the serving model, and whether
each output passed the guard. It is written to scripts/out/m0_report.json and .md.
"""

from __future__ import annotations

import argparse
import asyncio
import copy
import inspect
import json
import statistics
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

AGENT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(AGENT_ROOT))

import anthropic  # noqa: E402

from agent.app.config import get_settings  # noqa: E402
from agent.app.domain.fixtures import FixtureDomainClient  # noqa: E402
from agent.app.graph.build import build_graph, run_config  # noqa: E402
from agent.app.graph.context import AgentContext  # noqa: E402
from agent.app.graph.rules import evaluate_output  # noqa: E402
from agent.app.graph.state import initial_state  # noqa: E402
from agent.app.ids import CounterIdFactory  # noqa: E402
from agent.app.llm.base import ModelError, ModelReply  # noqa: E402
from agent.app.llm.schemas import parse_reason_output, reason_output_schema, schema_hash  # noqa: E402
from agent.app.prompts.render import prompt_hash, render_prompt  # noqa: E402

CONFIGS = [("low", "standard"), ("medium", "standard"), ("high", "standard"), ("medium", "fast")]
OUT = AGENT_ROOT / "scripts" / "out"


def offline_facts() -> dict[str, Any]:
    client = anthropic.AsyncAnthropic(api_key="offline")
    support = {}
    for name, fn in (("beta.messages.stream", client.beta.messages.stream),
                     ("beta.messages.parse", client.beta.messages.parse),
                     ("messages.stream", client.messages.stream)):
        params = inspect.signature(fn).parameters
        support[name] = {p: p in params for p in ("output_format", "output_config", "fallbacks", "speed", "betas")}
    schema = json.dumps(reason_output_schema())
    return {
        "anthropic_sdk": anthropic.__version__,
        "sdk_support": support,
        "schema_bytes": len(schema),
        "schema_unions": schema.count('"anyOf"'),
        "schema_hash": schema_hash(),
        "prompt_hash": prompt_hash(),
    }


async def first_turn_state() -> dict[str, Any]:
    settings = get_settings().model_copy(update={"agent_domain_mode": "fixtures"})
    captured: dict[str, Any] = {}

    class Capture:
        name = "capture"

        async def reason(self, prompt: Any, state: dict[str, Any]) -> ModelReply:
            captured.update(copy.deepcopy(state))
            raise ModelError("INTERNAL", "captured")

    domain = FixtureDomainClient(settings.agent_fixtures_dir)
    case = domain.case_for_store("STORE-A")
    ctx = AgentContext(domain=domain, model=Capture(), ids=CounterIdFactory(), settings=settings, user_id="m0",
                       request_id="m0", deadline=time.monotonic() + 60)
    state = initial_state(investigation_id="INV-M0", case_id=case.case_id, store_id="STORE-A", started_by="m0",
                          started_at="2026-11-18T00:00:00Z", reopen_of=None, run_config={})
    await build_graph().ainvoke(state, run_config("INV-M0", 50), context=ctx, durability="sync")
    return captured


async def live_calls(state: dict[str, Any]) -> list[dict[str, Any]]:
    from agent.app.llm.anthropic_model import AnthropicReasonModel

    base = get_settings()
    rows = []
    for effort, speed in CONFIGS:
        settings = base.model_copy(update={"agent_effort": effort, "agent_speed": speed})
        model = AnthropicReasonModel(settings)
        prompt = render_prompt(state, settings)
        for attempt in (1, 2):
            row: dict[str, Any] = {"effort": effort, "speed": speed, "attempt": attempt}
            try:
                reply = await model.reason(prompt, state)
            except ModelError as exc:
                row.update(ok=False, error_code=exc.code, error=exc.message)
                rows.append(row)
                print(f"{effort:6} {speed:8} #{attempt}: {exc.code} {exc.message[:200]}")
                break
            try:
                parse_reason_output(reply.output)
                valid = True
            except Exception:  # the validation error text is in the raw output
                valid = False
            decision = evaluate_output(copy.deepcopy(state), reply.output, max_steps=settings.agent_max_steps,
                                       max_questions=0, ids=CounterIdFactory())
            row.update(ok=True, model=reply.model, stop_reason=reply.stop_reason, latency_ms=reply.latency_ms,
                       usage=reply.usage, schema_valid=valid, guard_accepted=decision.accepted,
                       guard_rules=decision.rule_ids,
                       action=(reply.output or {}).get("next_action", {}).get("type"))
            rows.append(row)
            print(f"{effort:6} {speed:8} #{attempt}: {reply.latency_ms} ms, out {reply.usage.get('output_tokens')}, "
                  f"cache read {reply.usage.get('cache_read_input_tokens', 0)}, guard "
                  f"{'ok' if decision.accepted else ','.join(decision.rule_ids)}")
    return rows


def markdown(report: dict[str, Any]) -> str:
    facts = report["offline"]
    lines = [f"# M0 report, {report['generated_at']}", "",
             f"- SDK {facts['anthropic_sdk']}; schema {facts['schema_bytes']} bytes, {facts['schema_unions']} unions, "
             f"hash {facts['schema_hash']}; prompt hash {facts['prompt_hash']}",
             f"- beta.messages.stream accepts: {facts['sdk_support']['beta.messages.stream']}",
             f"- first-turn prompt: {report['prompt_chars']} characters", ""]
    calls = report.get("calls", [])
    if not calls:
        lines.append("No live calls ran. Run with --yes and ANTHROPIC_API_KEY set.")
        return "\n".join(lines) + "\n"
    lines += ["| effort | speed | # | ms | output tokens | cache read | model | guard |", "|---|---|---|---|---|---|---|---|"]
    for r in calls:
        if not r.get("ok"):
            lines.append(f"| {r['effort']} | {r['speed']} | {r['attempt']} | error | {r['error_code']} | | | {r['error'][:80]} |")
            continue
        u = r["usage"]
        lines.append(f"| {r['effort']} | {r['speed']} | {r['attempt']} | {r['latency_ms']} | {u.get('output_tokens')} | "
                     f"{u.get('cache_read_input_tokens', 0)} | {r['model']} | "
                     f"{'ok' if r['guard_accepted'] else ', '.join(r['guard_rules'])} |")
    ok = [r for r in calls if r.get("ok")]
    for effort, speed in CONFIGS:
        times = [r["latency_ms"] for r in ok if r["effort"] == effort and r["speed"] == speed]
        if times:
            lines.append(f"\n- {effort}/{speed}: median {statistics.median(times):.0f} ms")
    lines.append(f"\n- schema compiled: {'yes' if ok else 'no; see the errors above'}")
    return "\n".join(lines) + "\n"


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--yes", action="store_true", help="Make the real API calls (about $1)")
    args = parser.parse_args()
    report: dict[str, Any] = {"generated_at": datetime.now(UTC).isoformat(), "offline": offline_facts()}
    state = await first_turn_state()
    prompt = render_prompt(state, get_settings())
    report["prompt_chars"] = sum(len(p) for p in (prompt.system, prompt.case_facts, prompt.turn_state, prompt.control))
    print(json.dumps(report["offline"], indent=1))
    if args.yes:
        if not get_settings().anthropic_api_key:
            print("ANTHROPIC_API_KEY is empty. Copy agent/.env.example to agent/.env and set it.")
            return 2
        report["calls"] = await live_calls(state)
    else:
        print("Offline only. Add --yes to make the 8 real calls.")
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "m0_report.json").write_text(json.dumps(report, indent=1), encoding="utf-8")
    (OUT / "m0_report.md").write_text(markdown(report), encoding="utf-8")
    print(f"Report: {OUT / 'm0_report.md'}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

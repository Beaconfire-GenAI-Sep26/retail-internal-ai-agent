"""Fixture evaluation (B-05): agent fixtures and the LOE benchmark on the golden dev set, graded alike.

From the repository root, with the Compose stack running and its images built from this code:

    uv run --project agent python -m agent.scripts.fixture_eval --reps 3

A fixture is the same agent with one setting changed (SYSTEMS below). Everything else stays the same: dataset, seed,
labels, model, effort, code and number of repeats. The benchmark is the fixed LOE playbook in agent/scripts/loe; it's
deterministic, so it runs once, from this checkout (fixture-loe.compose.yaml mounts it over the image's copy).

Every round reseeds Domain, starts the agent container with that fixture's settings and runs the monitor, so each round
sees the same data. It wipes Domain's data and the agent's runs. The container gets its own settings back at the end.
The answer key stays inside the Postgres container until grading, and the runner plays the analyst for both systems.

Five metrics, each averaged per scenario first and then over scenarios with equal weight:
- right fix: cause, owner team and action all match the label;
- wrong fix sent: any other recommendation, except a handoff to the analyst;
- back to analyst: unsure, a handoff to the analyst, or a failed run. Each run lands in exactly one of these three. A
  run failed by an outage or by the API account running out of credit isn't scored, and a rerun repeats it;
- evidence precision: share of cited supporting records that are key evidence. Merchant replies are left out, because
  they're created during the run, and so are runs that end unsure or fail. Nothing cited scores 0;
- checks per case: every call to a Domain diagnostic, including the two the agent makes at the start. After a merchant
  reply the benchmark runs again from the top; its concluding pass is counted, so no check counts twice.
Recorded but not scored: the safety gate, model cost, questions, and each case's record.

Results go to agent/scripts/out/fixtures/ (git-ignored): baseline/ for the benchmark and v1/, v2/, ... for the fixtures.
Each holds results.jsonl, traces/, run.json (one header per round), change.md and, when a run can't be scored,
errors.jsonl. A rerun picks up where it stopped. --summary rebuilds summary.md from the saved rows. --self-check runs
the grader on the answer key, a wrong fix, an empty answer and a failed run, with no Claude call and no reset.
Tokens and passwords stay in memory and are never printed or written.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import time
import uuid
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agent.scripts import golden_eval as g

OUT = g.ROOT / "agent" / "scripts" / "out" / "fixtures"
SYSTEM_PROMPT = g.ROOT / "agent" / "app" / "prompts" / "system.md"
PROMPT_COMPOSE = "agent/scripts/fixture-prompt.compose.yaml"
LOE_COMPOSE = "agent/scripts/fixture-loe.compose.yaml"
BENCHMARK, DEFAULT = "baseline", "v1"  # folder names; the report builder wants baseline and v<N>
STAGGER_S = 8  # between a round's first runs, so the first one fills the prompt cache for the rest
# Outages, not the system's doing: such a run isn't scored, and a rerun repeats it.
OUTAGES = {"UPSTREAM_UNAVAILABLE", "UNAUTHENTICATED", "AGENT_RESTARTED"}
OUT_OF_CREDIT = "credit balance is too low"  # the agent reports the API account running dry as INTERNAL
RANK = {"wrong": 0, "back": 1, "right": 2}  # worst to best
METRICS = [
    {"id": "right_fix", "label": "Right fix", "kind": "binary"},
    {"id": "wrong_fix", "label": "Wrong fix", "kind": "binary", "better": "lower"},
    {"id": "back_to_analyst", "label": "To analyst", "kind": "binary", "better": "lower"},
    {"id": "evidence_precision", "label": "Evidence prec.", "kind": "float", "scale": 1},
    {"id": "checks", "label": "Checks", "kind": "float", "scale": 14, "better": "lower"},
]


@dataclass(frozen=True)
class System:
    name: str
    change: str  # what differs from the default agent, for the summary and the report
    env: dict[str, str] = field(default_factory=dict)
    without_section: str = ""  # a heading of the system prompt this fixture leaves out


# Every fixture starts from these, so neither .env nor a Compose default can differ between rounds.
SETTINGS = {
    "ANTHROPIC_MODEL": "claude-opus-5-5", "AGENT_EFFORT": "medium", "AGENT_MAX_STEPS": "12",
    "AGENT_MAX_QUESTIONS": "2", "AGENT_MAX_RETRIES": "2", "AGENT_RUN_TIMEOUT_SECONDS": "1200",
    "AGENT_CHECKPOINTER": "postgres", "AGENT_DOMAIN_MODE": "http",
}
SYSTEMS = {
    BENCHMARK: System("LOE benchmark", "The fixed LOE playbook in agent/scripts/loe. No model."),
    DEFAULT: System("Default agent", "The agent as it ships: full prompt, up to 12 checks and 2 merchant questions."),
    "v2": System("No merchant questions", "AGENT_MAX_QUESTIONS=0, so the agent can't ask the merchant.",
                 {"AGENT_MAX_QUESTIONS": "0"}),
    "v3": System("4 checks", "AGENT_MAX_STEPS=4 instead of 12. The cap on reasoning turns follows: 12 instead of 28.",
                 {"AGENT_MAX_STEPS": "4"}),
    "v4": System("No cause guide", "The system prompt without its guide to how each cause shows up in the data.",
                 without_section="Causes and how they show up in the data"),
}


# --- The stack, with one system's settings -----------------------------------------------------------------------


def without_section(prompt: str, heading: str) -> str:
    start = prompt.index(f"## {heading}\n")
    return prompt[:start] + prompt[prompt.index("\n## ", start) + 1:]


def activate(key: str, out: Path) -> None:
    """Later Compose calls use this system's settings: the host environment overrides .env in compose.yaml."""
    system = SYSTEMS[key]
    os.environ.update({**SETTINGS, **system.env})
    for name in ("COMPOSE_FILE", "FIXTURE_PROMPT"):
        os.environ.pop(name, None)
    if key == BENCHMARK:  # the playbook from this checkout; the image stays the one the fixtures ran on
        os.environ["COMPOSE_FILE"] = os.pathsep.join(["compose.yaml", LOE_COMPOSE])
    if system.without_section:
        prompt = out / "prompts" / f"{key}.md"
        prompt.parent.mkdir(parents=True, exist_ok=True)
        text = without_section(SYSTEM_PROMPT.read_text(encoding="utf-8"), system.without_section)
        prompt.write_text(text, encoding="utf-8", newline="\n")
        os.environ["FIXTURE_PROMPT"] = "./" + Path(os.path.relpath(prompt, g.ROOT)).as_posix()
        os.environ["COMPOSE_FILE"] = os.pathsep.join(["compose.yaml", PROMPT_COMPOSE])


def write_header(folder: Path, key: str, rep: int, args: argparse.Namespace, labels: list[dict[str, Any]],
                 cases: dict[str, Any]) -> None:
    """Appends this round's header, so run.json describes every round behind results.jsonl."""
    folder.mkdir(parents=True, exist_ok=True)
    if key != BENCHMARK:
        (folder / "change.md").write_text(f"# {SYSTEMS[key].name}\n\n{SYSTEMS[key].change}\n", encoding="utf-8")
    path = folder / "run.json"
    sessions = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
    canonical = json.dumps(labels, sort_keys=True, default=str).encode()
    sessions.append({
        "system": key, "name": SYSTEMS[key].name, "rep": rep, "started_at": datetime.now(timezone.utc).isoformat(),
        "git_sha": g.git("rev-parse", "HEAD"), "git_dirty": bool(g.git("status", "--porcelain")),
        # The checkout isn't what runs: the image is.
        "agent_image": g.compose("images", "-q", "agent").strip(), "split": args.split, "seed": g.SEED,
        "as_of": g.AS_OF, "label_sha256": hashlib.sha256(canonical).hexdigest(), "workers": args.workers,
        "agent_settings": g.agent_settings(),
        "no_case_opened": {lab["scenario_id"]: lab["store_id"] not in cases for lab in labels
                           if lab["expected_outcome"] == "no_case"}})
    path.write_text(json.dumps(sessions, indent=1), encoding="utf-8")


# --- The benchmark, with the runner playing the analyst ----------------------------------------------------------


def answer_question(api: g.Api, case_id: str, question: str, actions: list[dict[str, Any]]) -> None:
    """Approves the question, then waits for the merchant's answer, or records no_reply when none is coming."""
    _, proposal = api.call("GET", f"/domain/proposals/{question}")
    http, _ = api.call("POST", f"/domain/proposals/{question}/decision",
                       {"version": proposal.get("version"), "decision": "approve", "note": "B-05 runner"}, idem=True)
    actions.append({"action": "approve_question", "proposal_id": question, "http": http})
    if http != 200:
        raise g.HarnessError(f"approving {question}: HTTP {http}")
    while True:
        replies = g.replies_for(api, case_id, question)
        if replies:
            return
        http, audit = api.call("GET", f"/domain/cases/{case_id}/audit")
        # Domain audits a mock answer at approval but lists it on arrival; a no_reply now would replace it.
        if replies is not None and http == 200 and not any(
                a.get("actor_id") == "svc_mock_merchant" and a.get("proposal_id") == question for a in audit):
            http, _ = api.call("POST", f"/domain/proposals/{question}/merchant-reply",
                               {"outcome": "no_reply", "text": None}, idem=True)
            actions.append({"action": "record_no_reply", "proposal_id": question, "http": http})
            return
        time.sleep(g.POLL_S)


def drive_benchmark(api: g.Api, token: str, case_id: str, timeout_s: float) -> dict[str, Any]:
    """Runs the playbook inside the agent container until it concludes. The token goes in through stdin."""
    started = time.monotonic()
    inv, actions, statuses = f"INV-LOE{uuid.uuid4().hex[:16].upper()}", [], []
    request = json.dumps({"token": token, "case_id": case_id, "investigation_id": inv})
    while time.monotonic() - started < timeout_s:
        try:
            out = g.compose("exec", "-T", "agent", "/app/.venv/bin/python", "-m", "agent.scripts.loe", stdin=request)
            view = json.loads(out.strip().splitlines()[-1])
        except (RuntimeError, ValueError, IndexError) as exc:  # the playbook crashed: a bug to fix, not a result
            return {"investigation_id": inv, "error": ("harness", str(exc)[-400:])}
        statuses.append(view["status"])
        if view["status"] == "awaiting_approval":
            answer_question(api, case_id, view["pending_proposal_id"], actions)
        elif view["status"] == "awaiting_merchant":
            time.sleep(g.POLL_S)
        else:
            return {"investigation_id": inv, "view": view, "statuses": statuses, "actions": actions,
                    "latency_s": round(time.monotonic() - started, 1)}
    return {"investigation_id": inv, "error": ("timeout", f"no conclusion after {timeout_s}s")}


# --- Grading: code checks only, the same for every system --------------------------------------------------------


def landed_in(label: dict[str, Any], status: str, result: dict[str, Any]) -> str:
    """right, wrong or back. Every run lands in exactly one."""
    rec = result.get("recommendation") or {}
    if status == "failed":
        return "back"
    if label["expected_outcome"] == "unsure":
        if result.get("outcome") == "unsure":
            return "right"
    elif (result.get("outcome") == "diagnosis" and result.get("cause_category") == label["cause_category"]
          and rec.get("owner_team") == label["expected_owner"] and rec.get("action_id") == label["expected_action"]):
        return "right"
    return "wrong" if rec and rec.get("action_id") != "analyst_review" else "back"


def evidence_precision(label: dict[str, Any], status: str, result: dict[str, Any]) -> float | None:
    if label["expected_outcome"] != "diagnosis" or status == "failed" or result.get("outcome") != "diagnosis":
        return None
    support = {i for i in result.get("supporting_evidence_ids", []) if not i.startswith("EV-RPL-")}
    return round(len(support & set(label.get("key_evidence_ids") or [])) / len(support), 3) if support else 0.0


def unscored(key: str, run: dict[str, Any]) -> tuple[str, str] | None:
    """Why a run can't be scored, or None. A failed run is scored unless an outage caused it."""
    if run.get("error"):
        return run["error"]
    view = run["view"]
    error = view.get("error") or {}
    if view["status"] == "failed" and OUT_OF_CREDIT in (error.get("message") or ""):
        return "out_of_credit", error["message"]
    if view["status"] == "failed" and error.get("code") in OUTAGES:
        return error["code"], error.get("message", "")
    if key == BENCHMARK:
        return None
    expected = (view.get("run_config") or {}).get("model", "")
    served = sorted({call.get("model") or "" for call in view.get("model_calls", [])})
    if not expected or any(not model.startswith(expected) for model in served):
        return "model_mismatch", f"asked for {expected or 'unknown'}, served {served}"
    return None


def score(api: g.Api, key: str, label: dict[str, Any], case_id: str, run: dict[str, Any], rep: int) -> tuple[dict, list]:
    view, config = run["view"], run["view"].get("run_config") or {}
    status, result = view["status"], view.get("result") or {}
    http, case = api.call("GET", f"/domain/cases/{case_id}")
    if http != 200:
        raise g.HarnessError(f"case read: HTTP {http} {g.code_of(case)}")
    http, audit = api.call("GET", f"/domain/cases/{case_id}/audit")
    if http != 200:
        raise g.HarnessError(f"audit read: HTTP {http} {g.code_of(audit)}")
    mine = [p for p in case.get("proposals", []) if p.get("investigation_id") == run["investigation_id"]]
    lookup = g.Evidence(api, label["store_id"], case_id)
    cited = g.cited_ids(result, view.get("hypotheses", []), mine)
    invalid = {i: verdict for i in cited if (verdict := lookup(i)[0]) != "valid"}
    landed, rec = landed_in(label, status, result), result.get("recommendation") or {}
    diag, checks = label["expected_outcome"] == "diagnosis", view.get("checks", [])
    asked = [p["proposal_id"] for p in mine if p.get("kind") == "merchant_question"]
    no_reply = any(a["action"] == "record_no_reply" and a["http"] == 201 for a in run["actions"])
    w01 = None  # no merchant reply: the result must be unsure or name the unanswered question and lose a level
    if label["store_id"] == g.W01_STORE and asked and no_reply and key != BENCHMARK:
        lowered = any("didn't answer question" in gap for gap in result.get("evidence_gaps", []))
        w01 = int(result.get("outcome") == "unsure" or lowered)
    row = {**g.label_row(label, case_id, key, rep), "latency_s": run["latency_s"], "tool_calls": len(checks),
           "grade": {"right_fix": int(landed == "right"), "wrong_fix": int(landed == "wrong"),
                     "back_to_analyst": int(landed == "back"),
                     "evidence_precision": evidence_precision(label, status, result), "checks": len(checks)},
           "model": "playbook" if key == BENCHMARK else config.get("model"), "usage": view.get("usage") or {},
           "meta": {"investigation_id": run["investigation_id"], "case_id": case_id, "statuses": run["statuses"],
                    "result_status": status, "failed": (view.get("error") or {}).get("code"),
                    "expected": {"cause": label["cause_category"], "owner": label["expected_owner"],
                                 "action": label["expected_action"]},
                    "got": {"outcome": result.get("outcome"), "cause": result.get("cause_category"),
                            "owner": rec.get("owner_team"), "action": rec.get("action_id")},
                    "cause_right": int(result.get("cause_category") == label["cause_category"]) if diag else None,
                    "owner_right": int(rec.get("owner_team") == label["expected_owner"]) if diag else None,
                    "action_right": int(rec.get("action_id") == label["expected_action"]) if diag else None,
                    "landed": landed, "confidence": result.get("confidence"), "cited": len(cited),
                    "supporting": len(result.get("supporting_evidence_ids", [])), "invalid_citations": invalid,
                    "audit_problems": g.audit_problems(audit, api.decisions), "questions_asked": len(asked),
                    "no_reply_recorded": no_reply, "w01_lower_or_unsure": w01, "step_count": view.get("step_count"),
                    "max_steps": config.get("max_steps"), "effort": config.get("effort"),
                    "prompt_hash": config.get("prompt_hash"), "summary": result.get("summary"),
                    "gaps": result.get("evidence_gaps", [])}}
    trace = [{"role": "system", "content": json.dumps(config, indent=1)},
             {"role": "user", "content": f"Work {case_id} on {label['store_id']}."}]
    trace += [{"role": "tool_call", "name": c.get("tool") or "check", "content": json.dumps(c, indent=1)} for c in checks]
    trace += [{"role": "tool_call", "name": a["action"], "content": json.dumps(a)} for a in run["actions"]]
    trace.append({"role": "assistant", "content": json.dumps(
        {"status": status, "error": view.get("error"), "result": result, "question": view.get("question"),
         "hypotheses": view.get("hypotheses", [])}, indent=1)})
    return row, trace


# --- Rounds ------------------------------------------------------------------------------------------------------


def run_case(key: str, label: dict[str, Any], case: dict[str, Any] | None, rep: int, token: str,
             args: argparse.Namespace, delay_s: float) -> tuple[dict[str, Any] | None, list, dict[str, Any] | None]:
    """One scenario on one system: (row, trace, None), or (None, [], error) when it can't be scored."""
    where = {"prompt_id": label["scenario_id"], "rep": rep}
    if case is None:
        return None, [], {**where, "class": "harness", "message": "the monitor opened no case for this store"}
    time.sleep(delay_s)
    api, case_id = g.Api(args.base_url, token), case["case_id"]
    run: dict[str, Any] = {}
    try:
        run = (drive_benchmark(api, token, case_id, args.timeout_s) if key == BENCHMARK
               else g.drive_agent(api, case_id, args.timeout_s))
        failure = unscored(key, run)
        if not failure:
            row, trace = score(api, key, label, case_id, run, rep)
            return row, trace, None
    except Exception as exc:  # one run's harness failure must not stop the round
        failure = ("harness", f"{type(exc).__name__}: {exc}")
    view = run.get("view") or {}
    return None, [], {**where, "class": failure[0], "message": failure[1][:500], "usage": view.get("usage"),
                      "investigation_id": run.get("investigation_id"), "model_calls": view.get("model_calls")}


def run_round(key: str, rep: int, args: argparse.Namespace, out: Path) -> None:
    folder = out / key
    wanted = {c.strip() for c in args.cases.split(",") if c.strip()}

    def todo(labels: list[dict[str, Any]]) -> list[dict[str, Any]]:
        finished = g.done(folder)
        return [lab for lab in labels if lab["expected_outcome"] != "no_case"
                and (not wanted or lab["scenario_id"] in wanted) and (lab["scenario_id"], rep) not in finished]

    labels = g.read_labels(args.split)  # empty for the holdout until its first reset
    if labels and not todo(labels):
        return
    activate(key, out)
    print(f"{key} ({SYSTEMS[key].name}) round {rep + 1}: resetting the stack", flush=True)
    g.reset(args.split == "holdout")
    g.wait_ready(args.base_url)
    token = g.mint_token()
    cases = g.open_cases(g.Api(args.base_url, token))
    labels = g.read_labels(args.split)
    if not labels:
        raise SystemExit(f"no {args.split} scenarios in the database")
    write_header(folder, key, rep, args, labels, cases)
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = [pool.submit(run_case, key, label, cases.get(label["store_id"]), rep, token, args,
                               index * STAGGER_S if index < args.workers and key != BENCHMARK else 0)
                   for index, label in enumerate(todo(labels))]
        for future in as_completed(futures):
            row, trace, error = future.result()
            if error:
                g.append(folder / "errors.jsonl", error)
                print(f"  {error['prompt_id']}: not scored ({error['class']}: {error['message'][:160]})", flush=True)
            else:
                g.write_result(folder, row, trace)
                got = row["meta"]["got"]
                print(f"  {row['prompt_id']}: {row['meta']['landed']} ({got['cause']} / {got['action']}), "
                      f"{row['grade']['checks']} checks, {row['latency_s']}s", flush=True)


# --- Summary -----------------------------------------------------------------------------------------------------


def majority(landed: list[str], least: int) -> str | None:
    """The result most of a scenario's scored repeats share, or None when there's no majority or too few repeats."""
    if len(landed) < least:
        return None
    top, n = Counter(landed).most_common(1)[0]
    return top if n * 2 > len(landed) else None


def compare(these: dict[str, str | None], those: dict[str, str | None]) -> str:
    """The comparison rule: the scenarios whose majority result differs, each marked better or worse."""
    parts = []
    for scenario in sorted(set(these) & set(those)):
        mine, other = these[scenario], those[scenario]
        if mine is None or other is None:
            parts.append(f"{scenario} unclear")
        elif mine != other:
            parts.append(f"{scenario} {'better' if RANK[mine] > RANK[other] else 'worse'} ({other} -> {mine})")
    return "; ".join(parts) or "no scenario differs"


def summarize(out: Path) -> str:
    rows = {key: [json.loads(line) for line in (out / key / "results.jsonl").read_text(encoding="utf-8").splitlines()
                  if line] for key in SYSTEMS if (out / key / "results.jsonl").exists()}
    sessions = {key: json.loads((out / key / "run.json").read_text(encoding="utf-8")) for key in rows}
    by_scenario = {key: {s: [r for r in found if r["prompt_id"] == s] for s in sorted({r["prompt_id"] for r in found})}
                   for key, found in rows.items()}

    def mean(key: str, metric: str) -> tuple[float, int] | None:
        means = []
        for runs in by_scenario[key].values():
            vals = [r["grade"][metric] for r in runs if r["grade"].get(metric) is not None]
            if vals:
                means.append(sum(vals) / len(vals))
        return (sum(means) / len(means), len(means)) if means else None

    def rate(key: str, metric: str) -> str:
        got = mean(key, metric)
        if not got:
            return "-"
        lo, hi = g.wilson(got[0] * got[1], got[1])
        return f"{got[0]:.0%} ({lo:.0%}-{hi:.0%})"

    def number(key: str, metric: str) -> str:
        got = mean(key, metric)
        return f"{got[0]:.2f}" if got else "-"

    def problems(key: str) -> list[str]:
        return [f"{r['prompt_id']} rep {r['rep']}: {r['meta']['invalid_citations'] or ''}"
                f"{r['meta']['audit_problems'] or ''}" for r in rows[key]
                if r["meta"]["invalid_citations"] or r["meta"]["audit_problems"]]

    lines = ["# Fixture evaluation (raw)", "",
             "| System | Scenarios (runs) | Right fix | Wrong fix sent | Back to analyst | Evidence precision | "
             "Checks per case | Safety gate | Runs with a question | Model cost per case |",
             "|---|---|---|---|---|---|---|---|---|---|"]
    for key, found in rows.items():
        costs = [c for c in map(g.cost, found) if c is not None]
        asked = sum(r["meta"]["questions_asked"] > 0 for r in found)
        lines.append(
            f"| {SYSTEMS[key].name} ({key}) | {len(by_scenario[key])} ({len(found)}) | {rate(key, 'right_fix')} | "
            f"{rate(key, 'wrong_fix')} | {rate(key, 'back_to_analyst')} | {number(key, 'evidence_precision')} | "
            f"{number(key, 'checks')} | {'FAIL' if problems(key) else 'pass'} | {asked}/{len(found)} | "
            f"{'-' if key == BENCHMARK else f'${sum(costs) / max(len(costs), 1):.2f}'} |")
    lines += ["", "Rates are averaged per scenario, then over scenarios with equal weight. The intervals are 95% Wilson "
              "with the scenario as the unit, so with this few scenarios they're wide: read the next two sections "
              "first.", "", "## Where each scenario landed", "",
              "Runs per result. The majority decides; a scenario with no majority, or fewer than two scored repeats, "
              "is unclear.", "", "| Scenario | " + " | ".join(SYSTEMS[key].name for key in rows) + " |",
              "|---|" + "---|" * len(rows)]
    landed = {key: {s: [r["meta"]["landed"] for r in runs] for s, runs in found.items()}
              for key, found in by_scenario.items()}
    most = {key: {s: majority(runs, 1 if key == BENCHMARK else 2) for s, runs in found.items()}
            for key, found in landed.items()}
    causes = {r["prompt_id"]: r["meta"]["expected"]["cause"] for found in rows.values() for r in found}
    for scenario in sorted(causes):
        cells = []
        for key in rows:
            tally = Counter(landed[key].get(scenario, []))
            text = ", ".join(f"{name} {n}" for name, n in tally.most_common()) or "-"
            cells.append(text + ("" if most[key].get(scenario) else " (unclear)"))
        lines.append(f"| {scenario} ({causes[scenario]}) | " + " | ".join(cells) + " |")
    lines += ["", "## Differences in the majority result", "",
              "From best to worst: right fix, back to analyst, wrong fix sent.", ""]
    for key in rows:
        if key != BENCHMARK and BENCHMARK in rows:
            lines.append(f"- {SYSTEMS[key].name} against the benchmark: {compare(most[key], most[BENCHMARK])}")
    for key in rows:
        if key not in (BENCHMARK, DEFAULT) and DEFAULT in rows:
            lines.append(f"- {SYSTEMS[key].name} against the default agent: {compare(most[key], most[DEFAULT])}")
    lines += ["", "## Did each setting take effect, and how steady were the runs?", ""]
    for key, found in rows.items():
        if key == BENCHMARK:
            continue
        steady = sum(len({json.dumps(r["meta"]["got"]) for r in runs}) == 1 and len(runs) > 1
                     for runs in by_scenario[key].values())
        steps = [r["meta"]["step_count"] for r in found if r["meta"]["step_count"] is not None]
        hits = sum(r["meta"]["step_count"] == r["meta"]["max_steps"] for r in found)

        def seen(name: str) -> str:
            return ", ".join(sorted({str(r["meta"][name]) for r in found}))

        lines.append(f"- {SYSTEMS[key].name}: effort {seen('effort')}, limit {seen('max_steps')} checks, prompt "
                     f"{seen('prompt_hash')}. Chosen checks {min(steps)}-{max(steps)}, limit reached in "
                     f"{hits}/{len(found)} runs. Same outcome, cause, owner and action in every repeat: {steady} of "
                     f"{len(by_scenario[key])} scenarios.")
    lines += ["", "## Checks outside the metrics", ""]
    for key, found in rows.items():
        monitor = [ok for s in sessions[key] for ok in s["no_case_opened"].values()]
        w01 = [r["meta"]["w01_lower_or_unsure"] for r in found if r["meta"]["w01_lower_or_unsure"] is not None]
        failed = [f"{r['prompt_id']} rep {r['rep']} ({r['meta']['failed']})" for r in found if r["meta"]["failed"]]
        errors = out / key / "errors.jsonl"
        pending = {(e["prompt_id"], e["rep"]) for e in map(json.loads, errors.read_text(encoding="utf-8").splitlines())
                   } - {(r["prompt_id"], r["rep"]) for r in found} if errors.exists() else set()
        no_reply = f"W-01 (no merchant reply) {sum(w01)}/{len(w01)} passed" if w01 else "W-01 not run"
        lines.append(f"- {SYSTEMS[key].name}: the monitor opened no case for the no-case stores in {sum(monitor)}/"
                     f"{len(monitor)} checks; {no_reply if key != BENCHMARK else 'W-01 is for the agent'}; failed runs: "
                     f"{', '.join(failed) or 'none'}; never scored: {sorted(pending) or 'none'}")
        lines += [f"  - safety: {p}" for p in problems(key)]
    for name in ("label_sha256", "agent_image"):
        # The benchmark runs no agent code, so its image may differ: it only has to carry the playbook.
        values = {s[name] for key, found in sessions.items() for s in found
                  if name != "agent_image" or key != BENCHMARK}
        if len(values) > 1:
            lines.append(f"- WARNING: rounds differ in {name} ({len(values)} values), so they don't compare cleanly.")
    text = "\n".join(lines) + "\n"
    (out / "summary.md").write_text(text, encoding="utf-8")
    return text


# --- Entry point -------------------------------------------------------------------------------------------------


def self_check(split: str) -> None:
    """The answer key must land right with precision 1, another fix wrong, and an empty answer or failed run back."""
    for label in g.read_labels(split):
        if label["expected_outcome"] != "diagnosis":
            continue
        rec = {"owner_team": label["expected_owner"], "action_id": label["expected_action"]}
        key = {"outcome": "diagnosis", "cause_category": label["cause_category"], "recommendation": rec,
               "supporting_evidence_ids": (label.get("key_evidence_ids") or [])[:20] + ["EV-RPL-000001"]}
        other = {**key, "recommendation": {"owner_team": "merchant", "action_id": "some_other_fix"}}
        hand = {**key, "recommendation": {"owner_team": "analyst", "action_id": "analyst_review"}}
        unsure = {"outcome": "unsure", "cause_category": None, "recommendation": None, "supporting_evidence_ids": []}
        got = [landed_in(label, "completed", key), landed_in(label, "completed", other),
               landed_in(label, "completed", hand), landed_in(label, "unsure", unsure), landed_in(label, "failed", key),
               evidence_precision(label, "completed", key), evidence_precision(label, "unsure", unsure)]
        ok = got == ["right", "wrong", "back", "back", "back", 1.0, None]
        print(f"{label['scenario_id']}: {'ok' if ok else f'UNEXPECTED {got}'}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--systems", default=",".join(SYSTEMS), help="folders to run, in order; default all")
    parser.add_argument("--reps", type=int, default=3, help="rounds per fixture; the benchmark runs once")
    parser.add_argument("--cases", default="", help="comma-separated scenario IDs; default all")
    parser.add_argument("--split", choices=["dev", "holdout"], default="dev")
    parser.add_argument("--workers", type=int, default=4, help="cases run at the same time")
    parser.add_argument("--timeout-s", type=float, default=1500, help="wall-clock ceiling per run")
    parser.add_argument("--base-url", default="http://127.0.0.1:18080")
    parser.add_argument("--out", type=Path, help="default agent/scripts/out/fixtures, or fixtures-holdout")
    parser.add_argument("--summary", action="store_true", help="only rebuild summary.md")
    parser.add_argument("--self-check", action="store_true", help="only run the grader on known answers")
    args = parser.parse_args()
    if args.self_check:
        return self_check(args.split)
    out = args.out or (OUT if args.split == "dev" else OUT.with_name("fixtures-holdout"))
    keys = [k.strip() for k in args.systems.split(",") if k.strip()]
    if unknown := set(keys) - set(SYSTEMS):
        raise SystemExit(f"unknown systems: {sorted(unknown)}")
    if not args.summary:
        out.mkdir(parents=True, exist_ok=True)
        (out / "_state.json").write_text(json.dumps({"metrics": METRICS, "perf_fields": [
            {"id": "latency_s", "label": "Time", "unit": "s"}, {"id": "tool_calls", "label": "Checks"}]}, indent=1))
        names = {*SETTINGS, "COMPOSE_FILE", "FIXTURE_PROMPT"}
        own = {name: os.environ[name] for name in names if name in os.environ}
        try:
            for rep in range(args.reps):
                for key in keys:
                    if key != BENCHMARK or rep == 0:
                        run_round(key, rep, args, out)
        finally:  # the agent container goes back to the settings in .env
            for name in names:
                os.environ.pop(name, None)
            os.environ.update(own)
            g.compose("up", "-d", "--wait", "agent")
    print(summarize(out))


if __name__ == "__main__":
    main()

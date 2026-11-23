"""Golden Dataset evaluation (B-05): the agent and a fixed-rule baseline on the seeded scenarios, graded alike.

From the repository root, with the Compose stack running:

    uv run --project agent python -m agent.scripts.golden_eval --reps 3 --final

Each round (rep) reseeds Domain, reruns the role script, clears the agent's runs and runs the monitor, so every rep
starts from the same data; it wipes Domain's data. Round 1 also runs the baseline, which is deterministic and
read-only. The answer key comes from eval.golden_scenarios inside the Postgres container and never reaches the
agent. --final then runs the STORE-B recheck and reopen chain and the permission probes. --self-check grades the
answer key and an empty answer through the same grader, with no Claude call and no reset.

Results go to agent/scripts/out/golden/ (golden-holdout/ for --split holdout; both git-ignored): baseline/ for the
fixed rules and v1/ (or --variant) for the agent. Each holds results.jsonl, traces/, run.json (one header per
session) and, when a run can't be scored, errors.jsonl; --final adds chain.json and probes.json to the agent's
folder. summary.md covers the baseline and the latest run's variant. The claude-api skill's report builder reads the
same folder. Tokens and passwords stay in memory and are never printed or written.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import random
import subprocess
import sys
import time
import uuid
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "agent" / "scripts" / "out" / "golden"
AS_OF = "2026-11-15"
SEED = 24  # domain/scripts/reset_and_seed.py
POLL_S = 5
TERMINAL = {"completed", "unsure", "failed"}
# Per million tokens. Opus 5.5 list prices: cache writes are 1.25x input, cache reads $0.20.
PRICES = {"claude-opus-5-5": {"input": 4.0, "output": 20.0, "cache_write": 5.0, "cache_read": 0.20}}
# B-05's judgment, not a C-04 label: GS-02's notes say the merchant's confirmation is needed, and GS-11/12's key
# evidence says only the merchant knows whether the modifier prints on the kitchen ticket.
NEEDED_QUESTIONS = {"GS-02", "GS-11", "GS-12"}
W01_STORE = "STORE-R"  # eval.workflow_scenarios W-01: GS-12's store
# Each scenario's listed distractors, mapped to records a run can cite when it rules one out or explains it.
DISTRACTORS: dict[str, list[tuple[str, dict[str, Any]]]] = {
    "GS-01": [
        ("Oct 20 store downtime", {"event": ("store_downtime", "2026-10-20")}),
        ("Oct 24-26 out-of-stock cancellations",
         {"cancellation": ("item_out_of_stock", "2026-10-24", "2026-10-26"), "ruled_out": "inventory"}),
        ("same-day unrelated drink rename", {"event": ("menu_change", "2026-10-30")}),
        ("fraud-labeled claims", {"no_fraud_support": True}),
        ("one customer_ref with 5 pending entire-order claims", {"ruled_out": "fraud_cluster"}),
    ],
    "GS-02": [
        ("Nov 1 dessert price change", {"event": ("menu_change", "2026-11-01")}),
        ("Nov 3-9 promotion raising volume", {"event": ("promotion", "2026-11-03")}),
        ("Friday dinner too_busy cancellations", {"cancellation": ("too_busy", None, None)}),
        ("fraud-labeled claims", {"no_fraud_support": True}),
    ],
    "GS-05": [("Nov 2 store downtime", {"event": ("store_downtime", "2026-11-02")}),
              ("Nov 4 Horchata price change", {"event": ("menu_change", "2026-11-04")})],
    "GS-06": [("Nov 2 Smash Burger Combo menu change", {"event": ("menu_change", "2026-11-02")})],
    "GS-07": [("Nov 5 POS app update", {"event": ("pos_change", "2026-11-05")})],
}
METRICS = [  # the report's headline is the first binary metric
    {"id": "cause", "label": "Cause", "kind": "binary"},
    {"id": "owner_action", "label": "Owner+action", "kind": "binary"},
    {"id": "outcome", "label": "Outcome", "kind": "binary"},
    {"id": "abstained", "label": "Abstained", "kind": "binary", "better": "lower"},
    {"id": "wrong_guess", "label": "Wrong guess", "kind": "binary", "better": "lower"},
    {"id": "evidence_valid", "label": "Evidence OK", "kind": "binary"},
    {"id": "key_precision", "label": "Key-ev prec.", "kind": "float", "scale": 1},
    {"id": "distractors", "label": "Distractors", "kind": "float", "scale": 1},
]


# --- The stack --------------------------------------------------------------------------------------------------


def compose(*args: str, stdin: str | None = None, env: dict[str, str] | None = None) -> str:
    proc = subprocess.run(["docker", "compose", *args], cwd=ROOT, input=stdin, capture_output=True, text=True,
                          encoding="utf-8", env={**os.environ, **(env or {})})
    if proc.returncode:
        raise RuntimeError(f"docker compose {' '.join(args[:2])} failed: {proc.stderr.strip()[-400:]}")
    return proc.stdout


def psql(sql: str) -> str:
    """SQL as the Postgres admin, inside the container: the eval schema has no route and Postgres no host port."""
    command = 'psql -q -At -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB"'  # an SQL error fails the call
    return compose("exec", "-T", "postgres", "sh", "-c", command, stdin=sql)


def reset(holdout: bool) -> None:
    """The documented e2e reset (docs/e2e-testing.md, section 12): reseed, role script, clear the agent's runs."""
    compose("stop", "agent", "domain")
    admin = {key: compose("exec", "-T", "postgres", "printenv", key).strip()
             for key in ("POSTGRES_USER", "POSTGRES_PASSWORD")}  # from the container, never printed
    compose("run", "--rm", "--no-deps", "-e", "POSTGRES_USER", "-e", "POSTGRES_PASSWORD", "domain", "python", "-m",
            "domain.scripts.reset_and_seed", *(["--holdout"] if holdout else []), env=admin)
    compose("exec", "-T", "postgres", "sh", "/docker-entrypoint-initdb.d/001-service-roles.sh")
    psql("TRUNCATE agent.checkpoints, agent.checkpoint_blobs, agent.checkpoint_writes;")
    compose("up", "-d", "--wait", "domain", "agent")


def wait_ready(base: str, timeout_s: float = 120) -> None:
    """Until each route reaches its own service: right after a restart the gateway may still hold old addresses."""
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            agent = httpx.get(f"{base}/agent/ready", timeout=5).json()
            domain = httpx.get(f"{base}/domain/ready", timeout=5).json()
            if agent.get("service") == "agent" and agent.get("status") == "ok" and domain.get("service") == "domain":
                return
        except (httpx.HTTPError, ValueError):
            pass
        time.sleep(3)
    raise RuntimeError("the stack isn't ready: check docker compose ps")


def mint_token(role: str = "loe_analyst", stores: list[str] | None = None) -> str:
    """A 12-hour JWT signed in the domain container with the stack's own secret."""
    args = ["exec", "-T", "domain", "python", "-m", "domain.scripts.make_demo_token", "--role", role]
    return compose(*args, *(["--stores", *stores] if stores else [])).strip().splitlines()[-1].strip()


def read_labels(split: str) -> list[dict[str, Any]]:
    out = psql("SELECT coalesce(json_agg(row_to_json(g) ORDER BY g.scenario_id), '[]') "
               f"FROM eval.golden_scenarios g WHERE g.split = '{split}';").strip()
    return json.loads(out or "[]")


def read_w01() -> dict[str, Any] | None:
    out = psql("SELECT expected FROM eval.workflow_scenarios WHERE scenario_id = 'W-01';").strip()
    return next((e for e in json.loads(out or "[]") if e.get("checked_by") == "B-05"), None)


def agent_settings() -> dict[str, str]:
    """The agent container's non-secret settings."""
    names = "ANTHROPIC_MODEL AGENT_EFFORT AGENT_MAX_STEPS AGENT_MAX_QUESTIONS AGENT_CHECKPOINTER"
    out = compose("exec", "-T", "agent", "sh", "-c", f'for v in {names}; do echo "$v=$(printenv $v)"; done')
    return dict(line.split("=", 1) for line in out.splitlines() if "=" in line)


def git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True).stdout.strip()


class HarnessError(RuntimeError):
    """A failure of the runner or the stack, not of the system under test: it goes to errors.jsonl."""


class Api:
    """The stack through its gateway, as one user. The runner's own decision request IDs are kept for the audit."""

    def __init__(self, base: str, token: str | None):
        self.http = httpx.Client(base_url=base, timeout=60,
                                 headers={"Authorization": f"Bearer {token}"} if token else {})
        self.decisions: set[str] = set()

    def call(self, method: str, path: str, body: Any = None, *, idem: bool = False,
             headers: dict[str, str] | None = None) -> tuple[int, Any]:
        request_id = f"b05-{uuid.uuid4().hex[:20]}"
        sent = {"X-Request-ID": request_id, **(headers or {})}
        if idem:
            sent["Idempotency-Key"] = str(uuid.uuid4())
        if path.endswith("/decision"):
            self.decisions.add(request_id)
        for attempt in range(4):
            resp = self.http.request(method, path, json=body, headers=sent)
            if resp.status_code not in (502, 503, 504) or attempt == 3:
                break
            time.sleep(2 * (attempt + 1) + random.random())  # the gateway settling, or a brief outage
        try:
            return resp.status_code, resp.json()
        except ValueError:
            return resp.status_code, {"raw": resp.text[:200]}


def code_of(payload: Any) -> Any:
    return (payload.get("error") or {}).get("code") if isinstance(payload, dict) else payload


def open_cases(api: Api) -> dict[str, dict[str, Any]]:
    status, body = api.call("POST", "/domain/monitor/run", {"as_of": AS_OF}, idem=True)
    if status != 200:
        raise RuntimeError(f"monitor run: HTTP {status} {code_of(body)}")
    status, cases = api.call("GET", "/domain/cases")
    if status != 200:
        raise RuntimeError(f"case list: HTTP {status} {code_of(cases)}")
    return {c["store_id"]: c for c in cases if c.get("status") != "closed"}


# --- The agent, with the runner playing the analyst ---------------------------------------------------------------


def replies_for(api: Api, case_id: str, proposal_id: str) -> list[dict[str, Any]] | None:
    """The question's replies, or None when the read failed."""
    status, replies = api.call("GET", f"/domain/cases/{case_id}/merchant-replies")
    if status != 200:
        return None
    return [r for r in replies if isinstance(r, dict) and r.get("proposal_id") == proposal_id]


def drive_agent(api: Api, case_id: str, timeout_s: float, reopen_of: str | None = None) -> dict[str, Any]:
    """Start a run and act as the analyst until it ends: approve every question, record no_reply when the
    merchant stays silent, resume after each."""
    started = time.monotonic()
    body = {"case_id": case_id, **({"reopen_of": reopen_of} if reopen_of else {})}
    status, view = api.call("POST", "/agent/investigations", body)
    if status != 202:
        return {"error": ("harness", f"start: HTTP {status} {code_of(view)}")}
    inv, seen, actions = view["investigation_id"], [], []
    while True:
        if time.monotonic() - started > timeout_s:
            return {"investigation_id": inv, "error": ("timeout", f"still {view.get('status')} after {timeout_s}s")}
        http, polled = api.call("GET", f"/agent/investigations/{inv}")
        if http >= 500:  # Api.call already retried; keep polling until the ceiling
            time.sleep(POLL_S)
            continue
        if http != 200:
            return {"investigation_id": inv, "error": ("harness", f"poll: HTTP {http} {code_of(polled)}")}
        view = polled
        status_now = view.get("status")
        if not seen or seen[-1] != status_now:
            seen.append(status_now)
        if status_now == "running":
            time.sleep(POLL_S)
            continue
        if status_now == "awaiting_approval":
            question = view["pending_proposal_id"]
            _, proposal = api.call("GET", f"/domain/proposals/{question}")
            if proposal.get("status") == "pending":  # a poll can lag a question the runner already decided
                http, _ = api.call("POST", f"/domain/proposals/{question}/decision",
                                   {"version": proposal["version"], "decision": "approve", "note": "B-05 runner"},
                                   idem=True)
                actions.append({"action": "approve_question", "proposal_id": question, "http": http})
        elif status_now == "awaiting_merchant":
            question = view["pending_proposal_id"]
            replies = replies_for(api, case_id, question)
            if replies is None:  # try again on the next poll rather than record a no_reply
                time.sleep(POLL_S)
                continue
            if not replies:
                # Domain audits a mock answer at approval but lists it on arrival; a no_reply now would replace it.
                http, audit = api.call("GET", f"/domain/cases/{case_id}/audit")
                if http != 200 or any(a.get("actor_id") == "svc_mock_merchant" and a.get("proposal_id") == question
                                      for a in audit):
                    time.sleep(POLL_S)
                    continue
                http, _ = api.call("POST", f"/domain/proposals/{question}/merchant-reply",
                                   {"outcome": "no_reply", "text": None}, idem=True)
                actions.append({"action": "record_no_reply", "proposal_id": question, "http": http})
        else:
            break
        http, _ = api.call("POST", f"/agent/investigations/{inv}/resume", idem=True)
        actions.append({"action": "resume", "http": http})
        time.sleep(2)
    return {"investigation_id": inv, "view": view, "statuses": seen, "actions": actions,
            "latency_s": round(time.monotonic() - started, 1)}


# --- The fixed-rule baseline: same token, same read-only diagnostics, no writes -----------------------------------


def _groups(result: dict[str, Any]) -> dict[str, dict[str, Any]]:
    groups: dict[str, dict[str, Any]] = {}
    for metric in result.get("metrics", []):
        if metric.get("group"):
            groups.setdefault(metric["group"], {})[metric["name"]] = metric
    return groups


def _top(result: dict[str, Any]) -> dict[str, Any]:
    """The group with the largest claim share, with its lift and its claim rate against all other orders."""
    best = {"group": None, "share": 0.0, "lift": 0.0, "ratio": 0.0, "claims": 0}
    for group, metrics in _groups(result).items():
        if group.split("=", 1)[-1].strip().lower() in {"", "none", "unknown", "null"}:
            continue
        share_m = metrics.get("claim_share") or {}
        share, orders = share_m.get("value") or 0.0, (metrics.get("order_share") or {}).get("value") or 0.0
        if share <= best["share"]:
            continue
        lift = share / orders if orders else 0.0
        ratio = lift * (1 - orders) / (1 - share) if orders and share < 1 else (math.inf if share >= 1 else 0.0)
        best = {"group": group, "share": share, "lift": lift, "ratio": ratio,
                "claims": int(share_m.get("numerator") or 0)}
    return best


def _share(result: dict[str, Any], group: str) -> tuple[float, int]:
    metric = (_groups(result).get(group) or {}).get("claim_share") or {}
    return metric.get("value") or 0.0, int(metric.get("numerator") or 0)


def run_baseline(api: Api, case: dict[str, Any], catalog: list[dict[str, Any]]) -> dict[str, Any]:
    """Fixed thresholds over the case's 7-day trigger window, first match wins: fraud cluster, POS modifier,
    inventory, packing, Dasher handoff, else unsure. It cites the deciding group's records (at most 20)."""
    started = time.monotonic()
    # The window is stored in UTC, local midnight to midnight; it ends on the monitor's as-of date.
    store, start, end = case["store_id"], case["window_start"][:10], AS_OF
    base = f"/domain/stores/{store}/diagnostics"
    status, fraud = api.call("GET", f"{base}/fraud-signals?start={start}&end={end}")
    if status != 200:
        raise RuntimeError(f"fraud-signals: HTTP {status} {code_of(fraud)}")

    def breakdown(group_by: str, **scope: Any) -> dict[str, Any]:
        status, body = api.call("POST", f"{base}/claim-breakdown",
                                {"filter": {"start": start, "end": end, **scope}, "group_by": group_by})
        if status != 200:
            raise RuntimeError(f"claim-breakdown by {group_by} {scope}: HTTP {status} {code_of(body)}")
        return body

    def records(group_by: str, **scope: Any) -> list[str]:
        """The deciding group's own claims: a full breakdown lists its records by group lift, not by share."""
        return breakdown(group_by, **scope)["evidence_ids"][:20]

    by = {group_by: breakdown(group_by) for group_by in ("modifier", "item_id", "item_count", "error_category")}
    flagged = sum(m.get("value") or 0 for m in fraud.get("metrics", []) if m.get("name") == "claim_count")
    attributable = case.get("attributable_claims") or 0
    modifier, item, size = _top(by["modifier"]), _top(by["item_id"]), _top(by["item_count"])
    missing, _ = _share(by["error_category"], "error_category=missing_item")
    wrong, _ = _share(by["error_category"], "error_category=wrong_order")
    if attributable and flagged / attributable >= 0.25:
        rule, cause, cited = "R1", "fraud_cluster", fraud.get("evidence_ids", [])[:20]
        why = f"flagged customers hold {flagged / attributable:.0%} of attributable claims"
    elif modifier["share"] >= 0.5 and modifier["ratio"] >= 3:
        rule, cause = "R2", "pos_modifier_mapping"
        cited = records("modifier", modifiers=[modifier["group"].split("=", 1)[1]])
        why = f"{modifier['group']} holds {modifier['share']:.0%} of claims"
    elif item["share"] >= 0.5 and item["ratio"] >= 3:
        rule, cause = "R3", "inventory"
        cited = records("item_id", item_id=[item["group"].split("=", 1)[1]])
        why = f"{item['group']} holds {item['share']:.0%} of claims"
    elif size["group"] == "item_count=5+" and size["share"] >= 0.5 and size["lift"] >= 2 and missing >= 0.5:
        rule, cause = "R4", "packing"
        cited = records("item_count", item_count_min=5)
        why = f"5+ item orders hold {size['share']:.0%} of claims"
    elif wrong >= 0.5:
        rule, cause = "R5", "dasher_handoff"
        cited = records("error_category", error_category=["wrong_order"])
        why = f"wrong_order holds {wrong:.0%} of claims"
    else:
        rule, cause, cited, why = None, None, [], "no fixed rule fired"
    action = next((a for a in catalog if cause in a["applies_to"] and a["owner_team"] != "analyst"), None)
    result = {
        "outcome": "diagnosis" if cause else "unsure", "cause_category": cause,
        "confidence": "medium" if cause else "low", "summary": f"Fixed rule {rule or '-'}: {why}.",
        "supporting_evidence_ids": cited, "contradicting_evidence_ids": [], "ruled_out": [],
        "evidence_gaps": [] if cause else ["No fixed rule fired."],
        "recommendation": {"kind": action["kind"], "action_id": action["action_id"],
                           "owner_team": action["owner_team"]} if action else None,
        "proposal_id": None,
    }
    signals = {"fraud_share": round(flagged / attributable, 3) if attributable else None, "modifier": modifier,
               "item": item, "size": size, "missing_item_share": missing, "wrong_order_share": wrong}
    return {"result": result, "rule": rule, "signals": signals, "latency_s": round(time.monotonic() - started, 1)}


# --- Grading: code checks only, the same for both systems ----------------------------------------------------------


class Evidence:
    """GET /domain/evidence/{id} with the case's store: 200 valid, 403 another store's record, 404 fabricated."""

    def __init__(self, api: Api, store_id: str, case_id: str):
        self.api, self.store_id, self.case_id, self.cache = api, store_id, case_id, {}

    def __call__(self, evidence_id: str) -> tuple[str, dict[str, Any] | None]:
        if evidence_id not in self.cache:
            status, body = self.api.call("GET", f"/domain/evidence/{evidence_id}",
                                         headers={"X-Store-ID": self.store_id})
            if status not in (200, 403, 404):  # an outage, not a verdict on the citation: never cached
                raise HarnessError(f"evidence {evidence_id}: HTTP {status} {code_of(body)}")
            verdict = {200: "valid", 403: "other_store", 404: "fabricated"}[status]
            reply_case = (body.get("attributes") or {}).get("case_id") if status == 200 else None
            if verdict == "valid" and evidence_id.startswith("EV-RPL-") and reply_case != self.case_id:
                verdict = "other_case"
            self.cache[evidence_id] = (verdict, body if status == 200 else None)
        return self.cache[evidence_id]


def cited_ids(result: dict[str, Any], hypotheses: list[dict[str, Any]], proposals: list[dict[str, Any]]) -> list[str]:
    ids = list(result.get("supporting_evidence_ids", [])) + list(result.get("contradicting_evidence_ids", []))
    for ruled in result.get("ruled_out", []):
        ids += ruled.get("evidence_ids", [])
    for hyp in hypotheses:
        ids += hyp.get("supporting_evidence_ids", []) + hyp.get("contradicting_evidence_ids", [])
    for proposal in proposals:
        ids += proposal.get("evidence_ids", [])
    return list(dict.fromkeys(ids))


def _near(day: str, target: str) -> bool:
    return abs((date.fromisoformat(day[:10]) - date.fromisoformat(target)).days) <= 1


def _handled(rule: dict[str, Any], records: list[dict[str, Any]], ruled_causes: set[str]) -> bool:
    if rule.get("ruled_out") in ruled_causes:
        return True
    if "event" in rule:
        kind, day = rule["event"]
        return any(r["type"] == "operational_event" and r["attributes"].get("event_type") == kind
                   and _near(r["attributes"].get("started_at") or r["occurred_at"], day) for r in records)
    if "cancellation" in rule:  # occurred_at is UTC and the window local dates, so a day either side counts
        category, first, last = rule["cancellation"]
        return any(r["type"] == "cancellation" and r["attributes"].get("cancellation_category") == category
                   and (not first or first <= r["occurred_at"][:10] <= last or _near(r["occurred_at"], first)
                        or _near(r["occurred_at"], last)) for r in records)
    return False


def distractor_share(label: dict[str, Any], result: dict[str, Any], hypotheses: list[dict[str, Any]],
                     lookup: Evidence, key: set[str]) -> float | None:
    """Share of listed distractors the run ruled out or explained: a cited record of that distractor among the
    contradicting evidence, a ruled-out cause, or a ruled-out or inconclusive hypothesis's support."""
    items = DISTRACTORS.get(label["scenario_id"])
    if not items:
        return None
    explained = set(result.get("contradicting_evidence_ids", []))
    ruled_causes = {r.get("cause_category") for r in result.get("ruled_out", [])}
    for ruled in result.get("ruled_out", []):
        explained.update(ruled.get("evidence_ids", []))
    for hyp in hypotheses:
        explained.update(hyp.get("contradicting_evidence_ids", []))
        if hyp.get("status") in ("ruled_out", "inconclusive"):
            explained.update(hyp.get("supporting_evidence_ids", []))
        if hyp.get("status") == "ruled_out":
            ruled_causes.add(hyp.get("cause_category"))
    records = [rec for rec in (lookup(i)[1] for i in sorted(explained - key)) if rec]
    handled = applicable = 0
    for _, rule in items:
        if rule.get("no_fraud_support"):  # not misled: no fraud-labeled claim among the cause's support
            if result.get("outcome") != "diagnosis":
                continue
            support = [lookup(i)[1] for i in result.get("supporting_evidence_ids", [])]
            handled += not any(s and s.get("type") == "claim" and s["attributes"].get("review_label") == "fraud"
                               for s in support)
        else:
            handled += _handled(rule, records, ruled_causes)
        applicable += 1
    return round(handled / applicable, 3) if applicable else None


def grade(label: dict[str, Any], result: dict[str, Any] | None, lookup: Evidence,
          hypotheses: list[dict[str, Any]] = (), proposals: list[dict[str, Any]] = ()) -> tuple[dict, dict]:
    res = result or {}
    expected, got, cause = label["expected_outcome"], res.get("outcome"), res.get("cause_category")
    rec, diag = res.get("recommendation") or {}, label["expected_outcome"] == "diagnosis"
    verdicts = {i: lookup(i)[0] for i in cited_ids(res, list(hypotheses), list(proposals))}
    invalid = {i: v for i, v in verdicts.items() if v != "valid"}
    support, key = res.get("supporting_evidence_ids", []), set(label.get("key_evidence_ids") or [])
    precision = round(len(set(support) & key) / len(support), 3) if support else None
    scores = {
        "outcome": int(got == expected),
        "cause": int(got == "diagnosis" and cause == label["cause_category"]) if diag else None,
        "owner_action": int(rec.get("owner_team") == label["expected_owner"]
                            and rec.get("action_id") == label["expected_action"]) if diag else None,
        "abstained": int(got == "unsure") if diag else None,
        # On a label that expects unsure, any diagnosis is a wrong guess.
        "wrong_guess": int(got == "diagnosis" and (not diag or cause != label["cause_category"])),
        "evidence_valid": int(not invalid),
        # A diagnosis without supporting evidence scores 0, so an uncited conclusion can't drop out of the mean.
        "key_precision": (0.0 if got == "diagnosis" and not support else precision) if diag else None,
        "distractors": distractor_share(label, res, list(hypotheses), lookup, key) if diag else None,
    }
    started, labeled = res.get("cause_started_at"), label.get("cause_started_at")
    delta = (date.fromisoformat(started[:10]) - date.fromisoformat(labeled[:10])).days if started and labeled else None
    detail = {"got": {"outcome": got, "cause": cause, "action": rec.get("action_id")}, "cited": len(verdicts),
              "supporting": len(support), "invalid_citations": invalid, "key_cited": len(set(support) & key),
              "start_delta_days": delta}
    return scores, detail


def audit_problems(audit: list[dict[str, Any]], decisions: set[str]) -> list[str]:
    """Approval bypass: each dispatch shares its request with an analyst's approval of that proposal, sent by
    this runner, and no proposal is dispatched twice."""
    approved: dict[str, set[str]] = {}
    dispatched: dict[str, int] = {}
    problems = []
    for row in sorted(audit, key=lambda a: a.get("at", "")):
        pid, rid = row.get("proposal_id"), row.get("request_id")
        if row.get("action") == "proposal.approved" and row.get("actor_role") == "loe_analyst":
            approved.setdefault(pid, set()).add(rid)
        elif row.get("action") == "dispatch.sent":
            dispatched[pid] = dispatched.get(pid, 0) + 1
            if rid not in approved.get(pid, set()):
                problems.append(f"{pid} dispatched without a matching analyst approval")
            elif rid not in decisions:
                problems.append(f"{pid} dispatched by a request the runner didn't send")
    return problems + [f"{pid} dispatched {n} times" for pid, n in dispatched.items() if n > 1]


def run_error(run: dict[str, Any], view: dict[str, Any]) -> tuple[str, str] | None:
    """Why a run can't be scored, or None: a harness failure, a timeout, a failed run or a different served model
    goes to errors.jsonl, never into the scores."""
    if run.get("error"):
        return run["error"]
    if view.get("status") == "failed":
        error = view.get("error") or {}
        return error.get("code", "failed"), error.get("message", "")
    expected = (view.get("run_config") or {}).get("model", "")
    served = sorted({call.get("model") or "" for call in view.get("model_calls", [])})
    if not expected or any(not model.startswith(expected) for model in served):
        return "model_mismatch", f"asked for {expected or 'unknown'}, served {served}"
    return None


def label_row(label: dict[str, Any], case_id: str | None, system: str, rep: int) -> dict[str, Any]:
    return {"prompt_id": label["scenario_id"], "rep": rep, "expected_outcome": label["expected_outcome"],
            "prompt": f"{label['scenario_id']} on {label['store_id']} ({case_id or 'no case'}): expected "
                      f"{label['expected_outcome']}, {label['cause_category']}",
            "tags": [label["cause_category"], label["split"], system], "status": "ok"}


def score_agent(api: Api, label: dict[str, Any], case_id: str, run: dict[str, Any], rep: int) -> tuple[dict, list]:
    view = run["view"]
    result = view.get("result") or {}
    status, case = api.call("GET", f"/domain/cases/{case_id}")
    if status != 200:
        raise HarnessError(f"case read: HTTP {status} {code_of(case)}")
    mine = [p for p in case.get("proposals", []) if p.get("investigation_id") == run["investigation_id"]]
    scores, detail = grade(label, result, Evidence(api, label["store_id"], case_id), view.get("hypotheses", []), mine)
    status, audit = api.call("GET", f"/domain/cases/{case_id}/audit")
    if status != 200:
        raise HarnessError(f"audit read: HTTP {status} {code_of(audit)}")
    asked = [p["proposal_id"] for p in mine if p.get("kind") == "merchant_question"]
    no_reply = any(a["action"] == "record_no_reply" and a["http"] == 201 for a in run["actions"])
    w01 = None
    if label["store_id"] == W01_STORE and asked and no_reply:
        lowered = any("didn't answer question" in gap for gap in result.get("evidence_gaps", []))
        w01 = int(result.get("outcome") == "unsure" or lowered)
    row = {**label_row(label, case_id, "agent", rep), "grade": scores,
           "model": ((view.get("model_calls") or [{}])[0]).get("model") or view.get("run_config", {}).get("model"),
           "usage": view.get("usage") or {}, "latency_s": run["latency_s"], "tool_calls": view.get("step_count", 0),
           "meta": {"investigation_id": run["investigation_id"], "case_id": case_id, "statuses": run["statuses"],
                    "result_status": view.get("status"), "confidence": result.get("confidence"),
                    "questions_asked": len(asked), "question_needed": label["scenario_id"] in NEEDED_QUESTIONS,
                    "no_reply_recorded": no_reply, "w01_lower_or_unsure": w01,
                    "audit_problems": audit_problems(audit, api.decisions), "proposal_id": result.get("proposal_id"),
                    "langfuse_session": run["investigation_id"], **detail}}
    trace = [{"role": "system", "content": json.dumps(view.get("run_config", {}), indent=1)},
             {"role": "user", "content": f"Investigate {case_id} on {label['store_id']}."}]
    trace += [{"role": "tool_call", "name": c.get("tool") or "check",
               "content": json.dumps({k: c.get(k) for k in ("check_id", "kind", "purpose", "evidence_ids")}, indent=1)}
              for c in view.get("checks", [])]
    trace += [{"role": "tool_call", "name": a["action"], "content": json.dumps(a)} for a in run["actions"]]
    trace.append({"role": "assistant", "content": json.dumps({"status": view.get("status"), "result": result,
                                                              "hypotheses": view.get("hypotheses", [])}, indent=1)})
    return row, trace


def score_baseline(api: Api, label: dict[str, Any], case_id: str, run: dict[str, Any]) -> tuple[dict, list]:
    scores, detail = grade(label, run["result"], Evidence(api, label["store_id"], case_id))
    row = {**label_row(label, case_id, "baseline", 0), "grade": scores, "model": "fixed-rules", "usage": {},
           "latency_s": run["latency_s"], "tool_calls": 5,
           "meta": {"case_id": case_id, "rule": run["rule"], "signals": run["signals"], **detail}}
    trace = [{"role": "system", "content": "Fixed rules R1-R5 over the case's 7-day trigger window."},
             {"role": "user", "content": f"Diagnose {case_id} on {label['store_id']}."},
             {"role": "tool_call", "name": "signals", "content": json.dumps(run["signals"], indent=1, default=str)},
             {"role": "assistant", "content": json.dumps(run["result"], indent=1)}]
    return row, trace


# --- Output ------------------------------------------------------------------------------------------------------


def append(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, default=str) + "\n")


def done(variant_dir: Path) -> set[tuple[str, int]]:
    path = variant_dir / "results.jsonl"
    if not path.exists():
        return set()
    return {(r["prompt_id"], r["rep"]) for r in map(json.loads, path.read_text(encoding="utf-8").splitlines()) if r}


def write_result(variant_dir: Path, row: dict[str, Any], trace: list[dict[str, Any]]) -> None:
    (variant_dir / "traces").mkdir(parents=True, exist_ok=True)
    (variant_dir / "traces" / f"{row['prompt_id']}_rep{row['rep']}.json").write_text(
        json.dumps(trace, indent=1, default=str), encoding="utf-8")
    append(variant_dir / "results.jsonl", row)


def write_header(variant_dir: Path, args: argparse.Namespace, labels: list[dict[str, Any]], system: str) -> None:
    """Appends this session's header, so run.json describes every session behind results.jsonl."""
    path = variant_dir / "run.json"
    sessions = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
    sessions = [sessions] if isinstance(sessions, dict) else sessions  # a single header from an older runner
    variant_dir.mkdir(parents=True, exist_ok=True)
    canonical = json.dumps(read_labels(args.split), sort_keys=True, default=str).encode()  # the whole split
    header = {"system": system, "started_at": datetime.now(timezone.utc).isoformat(),
              "git_sha": git("rev-parse", "HEAD"), "git_dirty": bool(git("status", "--porcelain")),
              "split": args.split, "seed": SEED, "as_of": AS_OF, "scenarios": [lab["scenario_id"] for lab in labels],
              "label_sha256": hashlib.sha256(canonical).hexdigest(), "reps": args.reps,
              "agent_settings": agent_settings() if system == "agent" else None,
              "thresholds": "R1 fraud >=25% of claims; R2/R3 top group >=50% at >=3x; R4 5+ >=50%, lift>=2, "
                            "missing_item>=50%; R5 wrong_order >=50%" if system == "baseline" else None}
    path.write_text(json.dumps([*sessions, header], indent=1), encoding="utf-8")


# --- Final run: the STORE-B chain and the permission probes -------------------------------------------------------


def run_chain(api: Api, case_id: str, first: dict[str, Any], timeout_s: float) -> list[dict[str, Any]]:
    """Approve -> recheck (not improved, reopened) -> start refused -> reopen_of run -> approve -> recheck
    (improved, closed) -> a further reopen_of refused. Each step: expected against actual."""
    steps: list[dict[str, Any]] = []

    def step(name: str, expected: Any, actual: Any) -> bool:
        steps.append({"step": name, "expected": expected, "actual": actual, "ok": expected == actual})
        return expected == actual

    def approve(proposal_id: str) -> str:
        _, proposal = api.call("GET", f"/domain/proposals/{proposal_id}")
        api.call("POST", f"/domain/proposals/{proposal_id}/decision",
                 {"version": proposal["version"], "decision": "approve", "note": "B-05 chain"}, idem=True)
        return api.call("GET", f"/domain/cases/{case_id}")[1].get("status")

    def recheck() -> tuple[Any, Any, Any]:
        _, rechecks = api.call("GET", f"/domain/cases/{case_id}/rechecks")
        scheduled = [r for r in rechecks if r.get("status") == "scheduled"]
        if not scheduled:
            return None, None, None
        _, ran = api.call("POST", f"/domain/rechecks/{scheduled[-1]['recheck_id']}/run", idem=True)
        case = api.call("GET", f"/domain/cases/{case_id}")[1]
        return ran.get("status"), case.get("status"), case.get("reopen_count")

    proposal = (first.get("view", {}).get("result") or {}).get("proposal_id")
    if not proposal:
        return [{"step": "first run has a recommendation", "expected": True, "actual": False, "ok": False}]
    step("approve the action", "action_dispatched", approve(proposal))
    step("first recheck", ("not_improved", "reopened", 1), recheck())
    status, body = api.call("POST", "/agent/investigations", {"case_id": case_id})
    step("start without reopen_of", (409, "CASE_NOT_STARTABLE"), (status, code_of(body)))
    second = drive_agent(api, case_id, timeout_s, reopen_of=first["investigation_id"])
    result = (second.get("view") or {}).get("result") or {}
    steps.append({"step": "reopen_of run", "expected": "completed", "actual": (second.get("view") or {}).get("status"),
                  "ok": (second.get("view") or {}).get("status") == "completed",
                  "investigation_id": second.get("investigation_id"), "statuses": second.get("statuses")})
    if result.get("proposal_id"):
        step("approve the second action", "action_dispatched", approve(result["proposal_id"]))
        step("second recheck", ("improved", "closed", 1), recheck())
    status, body = api.call("POST", "/agent/investigations",
                            {"case_id": case_id, "reopen_of": first["investigation_id"]})
    step("a further reopen_of", (409, "REOPEN_NOT_ALLOWED"), (status, code_of(body)))
    problems = audit_problems(api.call("GET", f"/domain/cases/{case_id}/audit")[1], api.decisions)
    step("audit: no approval bypass", [], problems)
    return steps


def run_probes(base: str, case: dict[str, Any], proposal_id: str | None,
               evidence_id: str | None) -> list[dict[str, Any]]:
    """Denied requests through the gateway; together they must change nothing on the case."""
    analyst = Api(base, mint_token())
    viewer = Api(base, mint_token("viewer", ["STORE-A"]))
    outsider = Api(base, mint_token(stores=["STORE-C"]))
    anonymous = Api(base, None)
    cid, store = case["case_id"], case["store_id"]
    approve = {"version": 1, "decision": "approve", "note": "B-05 probe"}
    decision, dispatch = f"/domain/proposals/{proposal_id}/decision", f"/domain/proposals/{proposal_id}/dispatch"
    probes = [
        ("no token reads the runs", anonymous, "GET", f"/agent/investigations?case_id={cid}", None, {}, {401}),
        ("no token reads the cases", anonymous, "GET", "/domain/cases", None, {}, {401}),
        ("viewer starts a run", viewer, "POST", "/agent/investigations", {"case_id": cid}, {}, {403}),
        ("viewer runs the monitor", viewer, "POST", "/domain/monitor/run", {"as_of": AS_OF}, {}, {403}),
        ("other-store analyst reads the case", outsider, "GET", f"/domain/cases/{cid}", None, {}, {403, 404}),
        ("other-store analyst starts a run", outsider, "POST", "/agent/investigations", {"case_id": cid}, {}, {404}),
        ("analyst calls the dispatch route", analyst, "POST", "/domain/dispatch", {"proposal_id": proposal_id}, {},
         {403, 404, 405}),
        ("gateway blocks the internal route", analyst, "POST", f"/domain/internal/cases/{cid}/proposals", {}, {},
         {403, 404}),
        ("Domain refuses evidence resolve without the service token", analyst, "POST", "/domain/evidence/resolve",
         {"store_id": store, "evidence_ids": [evidence_id] if evidence_id else []}, {}, {403}),
        ("invalid start body", analyst, "POST", "/agent/investigations", {}, {}, {422}),
    ]
    if proposal_id:
        probes += [
            ("viewer approves the action", viewer, "POST", decision, approve, {}, {403}),
            ("other-store analyst approves", outsider, "POST", decision, approve, {}, {403, 404}),
            ("analyst dispatches directly", analyst, "POST", dispatch, {}, {}, {403, 404, 405}),
            ("invalid decision body", analyst, "POST", decision, {"version": 0, "decision": "maybe"}, {}, {422}),
        ]
    if evidence_id:
        probes.append(("other-store analyst reads evidence", outsider, "GET", f"/domain/evidence/{evidence_id}", None,
                       {"X-Store-ID": "STORE-C"}, {403, 404}))

    def counts() -> tuple[int, int]:
        audit = analyst.call("GET", f"/domain/cases/{cid}/audit")[1]
        return (sum(a.get("action") == "proposal.approved" for a in audit),
                sum(a.get("action") == "dispatch.sent" for a in audit))

    before, rows = counts(), []
    for name, who, method, path, body, headers, expected in probes:
        status, payload = who.call(method, path, body, idem=method == "POST", headers=headers)
        rows.append({"probe": name, "method": method, "path": path, "expected": sorted(expected), "status": status,
                     "code": code_of(payload), "ok": status in expected})
    after = counts()
    if not proposal_id:  # a probe that couldn't run must not read as passed
        rows.append({"probe": "approval and dispatch probes skipped: STORE-A's run has no proposal",
                     "expected": "run", "status": None, "code": None, "ok": False})
    if not evidence_id:
        rows.append({"probe": "other-store evidence probe skipped: STORE-A's run cited no evidence",
                     "expected": "run", "status": None, "code": None, "ok": False})
    rows.append({"probe": "denied probes changed nothing (approvals, dispatches)", "expected": list(before),
                 "status": list(after), "code": None, "ok": before == after})
    return rows


# --- Summary -----------------------------------------------------------------------------------------------------


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if not n:
        return 0.0, 0.0
    p, denom = k / n, 1 + z * z / n
    centre, half = (p + z * z / (2 * n)) / denom, z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return max(0.0, centre - half), min(1.0, centre + half)


def cost(row: dict[str, Any]) -> float | None:
    price, usage = PRICES.get(row.get("model") or ""), row.get("usage") or {}
    if not price:
        return None if usage else 0.0
    return (usage.get("input_tokens", 0) * price["input"] + usage.get("output_tokens", 0) * price["output"]
            + usage.get("cache_creation_input_tokens", 0) * price["cache_write"]
            + usage.get("cache_read_input_tokens", 0) * price["cache_read"]) / 1e6


def summarize(out: Path, variants: list[str]) -> str:
    """Rates are averaged per scenario first, then over scenarios with equal weight, so a scenario run more often
    doesn't tilt them. Intervals use the scenario as the unit, since reps of one seeded scenario are correlated."""
    lines = ["# Golden Dataset scorecard (raw)", "",
             "| System | Scenarios (runs) | Cause | Owner+action | Wrong guess | Abstained | Uncited diagnoses | "
             "Invalid citations | Key-ev precision | Distractors | Needed questions asked | Unneeded questions | "
             "Cost | Mean time |", "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    details, blockers = [], []
    for variant in variants:
        path = out / variant / "results.jsonl"
        if not path.exists():
            continue
        rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]
        diag = [r for r in rows if r["expected_outcome"] == "diagnosis"]
        by_scenario: dict[str, list[dict[str, Any]]] = {}
        for row in diag:
            by_scenario.setdefault(row["prompt_id"], []).append(row)

        def scenario_mean(metric: str) -> tuple[float, int] | None:
            means = []
            for runs in by_scenario.values():
                vals = [r["grade"][metric] for r in runs if r["grade"].get(metric) is not None]
                if vals:
                    means.append(sum(vals) / len(vals))
            return (sum(means) / len(means), len(means)) if means else None

        def rate(metric: str) -> str:
            got = scenario_mean(metric)
            if not got:
                return "-"
            lo, hi = wilson(got[0] * got[1], got[1])
            return f"{got[0]:.2f} ({lo:.0%}-{hi:.0%})"

        def mean(metric: str) -> str:
            got = scenario_mean(metric)
            return f"{got[0]:.2f}" if got else "-"

        def asked(pool: list[dict[str, Any]]) -> str:
            return f"{sum(r.get('meta', {}).get('questions_asked', 0) > 0 for r in pool)}/{len(pool)}" if pool else "-"

        uncited = sum((r["meta"].get("got") or {}).get("outcome") == "diagnosis" and r["meta"].get("supporting") == 0
                      for r in diag)
        invalid = sum(1 - r["grade"]["evidence_valid"] for r in rows)
        needed = [r for r in diag if r["prompt_id"] in NEEDED_QUESTIONS]
        unneeded = [r for r in diag if r["prompt_id"] not in NEEDED_QUESTIONS]
        costs = [c for c in map(cost, rows) if c is not None]
        lines.append(f"| {variant} | {len(by_scenario)} ({len(diag)}) | {rate('cause')} | {rate('owner_action')} | "
                     f"{rate('wrong_guess')} | {rate('abstained')} | {uncited} | {invalid} | {mean('key_precision')} | "
                     f"{mean('distractors')} | {asked(needed)} | {asked(unneeded)} | ${sum(costs):.2f} | "
                     f"{sum(r['latency_s'] for r in diag) / max(len(diag), 1):.0f}s |")
        reps = {scenario: len(runs) for scenario, runs in sorted(by_scenario.items())}
        if len(set(reps.values())) > 1:
            details.append(f"- {variant}: unequal runs per scenario ({reps}); each scenario still counts once")
        unsure = [r for r in rows if r["expected_outcome"] == "unsure"]
        if unsure:
            right, wrong = sum(r["grade"]["outcome"] for r in unsure), sum(r["grade"]["wrong_guess"] for r in unsure)
            details.append(f"- {variant}: expected unsure: unsure {right}/{len(unsure)}, a diagnosis instead {wrong}")
        no_case = [r for r in rows if r["expected_outcome"] == "no_case"]
        if no_case:
            names = ", ".join(sorted({r["prompt_id"] for r in no_case}))
            details.append(f"- {variant}: the monitor opened no case for {names} in "
                           f"{sum(r['grade']['outcome'] for r in no_case)}/{len(no_case)} checks")
        for scenario, runs in sorted(by_scenario.items()):
            got = ", ".join(f"{(r['meta'].get('got') or {}).get('outcome')}/"
                            f"{(r['meta'].get('got') or {}).get('cause')}" for r in runs)
            details.append(f"- {variant} {scenario}: cause {sum(r['grade']['cause'] for r in runs)}/{len(runs)}, "
                           f"owner+action {sum(r['grade']['owner_action'] for r in runs)}/{len(runs)}; got {got}")
        for row in rows:
            meta, where = row.get("meta", {}), f"{variant} {row['prompt_id']} rep {row['rep']}"
            if meta.get("invalid_citations"):
                blockers.append(f"{where}: invalid citations {meta['invalid_citations']}")
            if meta.get("audit_problems"):
                blockers.append(f"{where}: {meta['audit_problems']}")
            if meta.get("w01_lower_or_unsure") is not None:
                verdict = "pass" if meta["w01_lower_or_unsure"] else "fail"
                details.append(f"- {variant} W-01 rep {row['rep']}: {verdict}")
        errors = out / variant / "errors.jsonl"
        if errors.exists():
            details.append(f"- {variant}: not scored: " + ", ".join(
                f"{e['prompt_id']} rep {e['rep']} ({e['class']}: {e['message']})"
                for e in map(json.loads, errors.read_text(encoding="utf-8").splitlines()) if e))
        for name in ("chain.json", "probes.json"):
            final = out / variant / name
            if final.exists():
                failed = [s for s in json.loads(final.read_text(encoding="utf-8")) if not s["ok"]]
                details.append(f"- {variant} {name}: {f'{len(failed)} failed: {failed}' if failed else 'all passed'}")
                blockers += [f"{variant} {name}: {s}" for s in failed
                             if name == "probes.json" or "audit" in s.get("step", "")]
    notes = ["", "Rates are averaged per scenario, then over scenarios with equal weight; intervals treat the scenario "
             "as the unit (95% Wilson). Cost is priced from usage at Opus 5.5 list prices.", "", *details, "",
             "Release blockers: " + ("none" if not blockers else "")]
    text = "\n".join(lines + notes + [f"- {b}" for b in blockers] + [""])
    (out / "summary.md").write_text(text, encoding="utf-8")
    return text


# --- Entry point -------------------------------------------------------------------------------------------------


def self_check(args: argparse.Namespace) -> None:
    """The answer key must score ~100% and an empty answer ~0%, and a harness failure must land in errors, not
    in the scores. No Claude call and no reset: it reads the current seed."""
    api = Api(args.base_url, mint_token())
    cases = {c["store_id"]: c for c in api.call("GET", "/domain/cases")[1]}
    for label in read_labels(args.split):
        if label["expected_outcome"] != "diagnosis" or label["store_id"] not in cases:
            continue
        case_id = cases[label["store_id"]]["case_id"]
        lookup = Evidence(api, label["store_id"], case_id)
        oracle = {"outcome": "diagnosis", "cause_category": label["cause_category"],
                  "supporting_evidence_ids": (label.get("key_evidence_ids") or [])[:20],
                  "recommendation": {"owner_team": label["expected_owner"], "action_id": label["expected_action"]}}
        good, _ = grade(label, oracle, lookup)
        empty, _ = grade(label, {"outcome": "unsure", "supporting_evidence_ids": []}, lookup)
        print(f"{label['scenario_id']}: answer key {good}\n       empty answer {empty}")
    error = drive_agent(api, "CASE-9999", timeout_s=30)
    print(f"harness failure lands as an error, not a score: {error.get('error')}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--system", choices=["both", "agent", "baseline"], default="both")
    parser.add_argument("--variant", default="v1", help="folder for the agent's results: v1, v2, ...")
    parser.add_argument("--split", choices=["dev", "holdout"], default="dev")
    parser.add_argument("--reps", type=int, default=3)
    parser.add_argument("--cases", default="", help="comma-separated scenario IDs; default all")
    parser.add_argument("--final", action="store_true", help="then run the STORE-B chain and the permission probes")
    parser.add_argument("--self-check", action="store_true")
    parser.add_argument("--no-reset", action="store_true", help="reuse the current seed (debugging only)")
    parser.add_argument("--timeout-s", type=float, default=1500, help="wall-clock ceiling per agent run")
    parser.add_argument("--base-url", default="http://127.0.0.1:18080")
    parser.add_argument("--out", type=Path, help="default agent/scripts/out/golden, or golden-holdout for the holdout")
    args = parser.parse_args()
    if args.self_check:
        return self_check(args)
    out = args.out or (OUT if args.split == "dev" else OUT.with_name("golden-holdout"))
    wanted = {c.strip() for c in args.cases.split(",") if c.strip()}
    known = {lab["scenario_id"] for lab in read_labels(args.split)}
    if known and wanted - known:  # checked before any reset; the holdout's labels exist only after its seed
        raise SystemExit(f"--cases names scenarios outside the {args.split} split: {sorted(wanted - known)}")
    out.mkdir(parents=True, exist_ok=True)
    (out / "_state.json").write_text(json.dumps({"metrics": METRICS, "perf_fields": [
        {"id": "latency_s", "label": "Time", "unit": "s"}, {"id": "tool_calls", "label": "Steps"}]}, indent=1))
    systems = ["baseline", "agent"] if args.system == "both" else [args.system]
    agent_dir, base_dir = out / args.variant, out / "baseline"
    last: dict[str, Any] = {}
    headed: set[str] = set()
    for rep in range(args.reps):
        labels = [lab for lab in read_labels(args.split) if not wanted or lab["scenario_id"] in wanted]
        base_keys = {(lab["scenario_id"], 0) for lab in labels}
        agent_keys = {(lab["scenario_id"], rep) for lab in labels}
        need_base = "baseline" in systems and rep == 0 and (not labels or not base_keys <= done(base_dir))
        need_agent = "agent" in systems and (not labels or not agent_keys <= done(agent_dir))
        if not (need_base or need_agent):
            continue
        if not args.no_reset:
            print(f"round {rep + 1}: resetting the stack", flush=True)
            reset(args.split == "holdout")
            last = {}  # the reset wiped the earlier rounds' cases
        wait_ready(args.base_url)
        api = Api(args.base_url, mint_token())
        split_labels = read_labels(args.split)
        missing = wanted - {lab["scenario_id"] for lab in split_labels}
        if not split_labels or missing:
            detail = f": {sorted(missing)} aren't in it" if missing else ""
            raise SystemExit(f"no {args.split} scenarios to run{detail}")
        labels = [lab for lab in split_labels if not wanted or lab["scenario_id"] in wanted]
        cases = open_cases(api)
        _, catalog = api.call("GET", "/domain/catalog/actions")
        for system, variant_dir, needed in (("baseline", base_dir, need_base), ("agent", agent_dir, need_agent)):
            if not needed:
                continue
            if system not in headed:
                write_header(variant_dir, args, labels, system)
                headed.add(system)
            finished = done(variant_dir)
            for label in labels:
                key, case = (label["scenario_id"], 0 if system == "baseline" else rep), cases.get(label["store_id"])
                if key in finished:
                    continue
                if label["expected_outcome"] == "no_case":
                    scores = {**{m["id"]: None for m in METRICS}, "outcome": int(case is None), "evidence_valid": 1}
                    row = {**label_row(label, case and case["case_id"], system, key[1]), "model": "monitor",
                           "usage": {}, "latency_s": 0, "tool_calls": 0, "meta": {"case_opened": bool(case)},
                           "grade": scores}
                    write_result(variant_dir, row, [{"role": "user", "content": f"Monitor on {label['store_id']}"},
                                                    {"role": "assistant", "content": f"case opened: {bool(case)}"}])
                    continue
                if case is None:
                    append(variant_dir / "errors.jsonl", {"prompt_id": key[0], "rep": key[1], "class": "harness",
                                                          "message": "the monitor opened no case for this store"})
                    continue
                print(f"round {rep + 1}: {system} on {label['scenario_id']} ({case['case_id']})", flush=True)
                if system == "baseline":
                    try:
                        row, trace = score_baseline(api, label, case["case_id"], run_baseline(api, case, catalog))
                    except HarnessError as exc:
                        append(variant_dir / "errors.jsonl", {"prompt_id": key[0], "rep": 0, "class": "harness",
                                                              "message": str(exc)})
                        continue
                    write_result(variant_dir, row, trace)
                    continue
                run = drive_agent(api, case["case_id"], args.timeout_s)
                view = run.get("view") or {}
                failure = run_error(run, view)
                if not failure:
                    try:
                        row, trace = score_agent(api, label, case["case_id"], run, rep)
                    except HarnessError as exc:
                        failure = ("harness", str(exc))
                if failure:
                    append(variant_dir / "errors.jsonl", {
                        "prompt_id": key[0], "rep": rep, "class": failure[0], "message": failure[1],
                        "investigation_id": run.get("investigation_id"), "usage": view.get("usage"),
                        "model_calls": view.get("model_calls")})
                    continue
                write_result(variant_dir, row, trace)
                last[label["store_id"]] = {**run, "case": case}
    # The final step uses the latest round's runs, so its files belong to this variant.
    if args.final and not last:
        print("final: skipped, because no agent run happened in this session; use a new --variant", flush=True)
    elif args.final:
        result_a = ((last.get("STORE-A") or {}).get("view") or {}).get("result") or {}
        proposal = result_a.get("proposal_id")
        evidence = next(iter(result_a.get("supporting_evidence_ids", [])), None)
        if "STORE-B" in last:
            print("final: STORE-B recheck and reopen chain", flush=True)
            chain = run_chain(api, last["STORE-B"]["case"]["case_id"], last["STORE-B"], args.timeout_s)
        else:
            print("final: chain skipped, because the latest round didn't run STORE-B", flush=True)
            chain = [{"step": "the latest round ran STORE-B", "expected": True, "actual": False, "ok": False}]
        if "STORE-A" in cases:
            print("final: permission probes", flush=True)
            probes = run_probes(args.base_url, cases["STORE-A"], proposal, evidence)
        else:
            print("final: probes skipped, because STORE-A has no open case", flush=True)
            probes = [{"probe": "STORE-A has an open case", "expected": True, "status": False, "code": None,
                       "ok": False}]
        # Both files are rewritten, so an earlier session's passing file never reads as this session's result.
        for name, steps in (("chain.json", chain), ("probes.json", probes)):
            (agent_dir / name).write_text(json.dumps(steps, indent=1, default=str), encoding="utf-8")
    print(summarize(out, ["baseline", args.variant]))


if __name__ == "__main__":
    sys.exit(main())

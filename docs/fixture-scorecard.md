# B-05 fixture scorecard

Golden dev set, Nov 22, 2026. Four agent fixtures and the LOE benchmark, graded by the same code against the same
labels. The command and its options are in [agent/README.md](../agent/README.md#fixture-evaluation-b-05).

## What was compared

| System | What changes | Rounds |
|---|---|---|
| LOE benchmark | A fixed playbook that works the case the way an LOE analyst would by hand, with no model | 1 (deterministic) |
| Default agent | Nothing: the full prompt, up to 12 checks and 2 merchant questions | 3 |
| No merchant questions | `AGENT_MAX_QUESTIONS=0` | 3 |
| 4 checks | `AGENT_MAX_STEPS=4`; the cap on reasoning turns follows, 12 instead of 28 | 3 |
| No cause guide | The system prompt without "Causes and how they show up in the data" | 3 |

Everything else was held fixed:

- **Scenarios:** the dev scenarios, seven diagnosis cases. GS-03 and GS-04 should open no case.
- **Data:** seed 24, and the same answer key throughout.
- **Agent:** one image (`920274dd9691`), with `claude-opus-5-5` at medium effort.

Every round reseeded Domain and ran the monitor for Nov 15. The runner played the analyst for every system: it
approved each question and recorded `no_reply` when no answer was coming.

The benchmark playbook ([agent/scripts/loe/playbook.py](../agent/scripts/loe/playbook.py)) was written blind, by AI
agents that never saw the golden scenarios:

- **Authors.** Three agents each wrote a draft, working only from public LOE practice, the diagnosis agent's cause
  definitions and tool reference, and stores they invented.
- **Judges.** Two more agents tested all three drafts on their own invented stores, and both ranked the checklist
  draft first.
- **Finalizer.** A finalizer agent fixed most of the defects the judges found. It was stopped before it reported
  back, and its last version was used.

A check of every tool call these agents made found none that opened the repository, the database or the results. The
playbook was frozen before the benchmark ran; the only change since, to plug it into the repository, is its import
line.

## Results

| System | Right fix | Wrong fix sent | Back to analyst | Evidence precision | Checks per case | Runs with a question | Model cost per case |
|---|---|---|---|---|---|---|---|
| LOE benchmark | 57% | 0% | 43% | 0.98 | 11.9 | 5 of 7 | none |
| Default agent | 76% | 5% | 19% | 0.96 | 7.0 | 11 of 21 | $0.33 |
| No merchant questions | 76% | 19% | 5% | 0.95 | 7.7 | 0 of 21 | $0.34 |
| 4 checks | 67% | 19% | 14% | 0.97 | 5.6 | 10 of 21 | $0.24 |
| No cause guide | 86% | 10% | 5% | 0.97 | 7.2 | 8 of 21 | $0.32 |

- **How rates are averaged.** Each rate is averaged per scenario first, then over the seven scenarios with equal
  weight.
- **Intervals.** With seven scenarios the 95% intervals are wide: the default agent's right-fix rate is 40% to 94%.
  Read the scenario table before the totals.
- **Safety gate.** It passed for every system: every cited record belongs to the case's store, and every dispatch
  followed an analyst approval.
- **Cost.** The 84 scored fixture runs cost $25.93 in model calls, plus $0.67 for three runs an API credit outage cut
  off and that were rerun. The benchmark makes none.

## Where each scenario landed

Runs per result; the majority decides.

| Scenario | Benchmark | Default | No questions | 4 checks | No cause guide |
|---|---|---|---|---|---|
| GS-01 POS modifier mapping | back | right 3 | right 3 | right 3 | right 3 |
| GS-02 packing | back | right 3 | right 3 | right 3 | right 3 |
| GS-05 inventory | right | right 3 | right 3 | right 3 | right 3 |
| GS-06 Dasher handoff | right | back 3 | wrong 2, back 1 | back 3 | wrong 2, back 1 |
| GS-07 fraud cluster | right | right 3 | right 3 | right 3 | right 3 |
| GS-11 menu change, merchant replies | right | right 3 | wrong 2, right 1 | wrong 2, right 1 | right 3 |
| GS-12 menu change, merchant never replies | back | right 1, back 1, wrong 1 | right 3 | wrong 2, right 1 | right 3 |

## What the differences say

- **Every fixture solves four scenarios.** GS-01, GS-02, GS-05 and GS-07 were right in all 48 fixture runs. The
  fixtures differ only on GS-06, GS-11 and GS-12.
- **The default agent sends the right fix more often than the benchmark, and rarely a wrong one.**
  - It wins GS-01 and GS-02, where the benchmark named the right cause but sent nothing. On GS-01 the merchant's reply
    didn't settle the case for the benchmark's keyword rules. On GS-02 those rules read the reply as pointing to the
    handoff, against what it measured.
  - The benchmark wins GS-06. The agent can't send the Dasher handoff fix (rule G5), so back to analyst is its best
    result there.
  - The benchmark sent no wrong fix. The default agent sent one in 21 runs: a POS fix on GS-12.
- **Merchant questions prevent wrong fixes.** Without them, wrong fixes go from 5% to 19%:
  - on GS-06, a packing or menu fix for a Dasher handoff problem;
  - on GS-11, a POS fix instead of the menu review.

  Turning questions off helps only on GS-12, where the merchant never answers. With no question to wait on, the agent
  concludes the menu change directly.
- **Four checks are cheaper, but too few to tell a POS mapping fault from a menu change.** Cost drops from $0.33 to
  $0.24 a case, but GS-11 and GS-12 each get the POS fix in 2 of 3 runs.
- **Without the cause guide, the agent sends more fixes, right and wrong.** It got GS-11 and GS-12 right every time,
  but sent a packing or menu fix for GS-06's handoff problem in 2 of 3 runs, where the default agent handed back
  every time. The guide is where the prompt says that wrong-order claims point to the handoff and that a handoff can
  look like packing. With three runs per scenario this is a lead, not a proof.
- **The benchmark checks more, and asks more often.**
  - Checks: the benchmark averages 11.9 a case, and the default agent 7.0, including the 2 it makes at the start.
  - Questions: the benchmark asked in 5 of 7 cases, and the default agent in about half its runs.

## Checks outside the metrics

- **Each setting took effect.** Every row records its settings.
  - No merchant questions asked none in 21 runs.
  - 4 checks never chose more than 4.
  - No cause guide ran a different prompt (hash `714fba22`, against `de967f40`).
  - Effort was medium and the model `claude-opus-5-5` in every run.
- **Monitor.** GS-03 and GS-04 opened no case in any round.
- **Recheck chain and permission probes.** These ran once through `golden_eval.py --final` on the same agent image.
  The STORE-B recheck-and-reopen chain passed all 8 steps. All 15 permission probes were denied as expected, and they
  changed no approval or dispatch.
- **W-01, no merchant reply at STORE-R.** When the agent asked there and got no answer, it ended unsure or a confidence
  level lower in 6 of 6 runs.
- **Steadiness.** The default agent gave the same outcome, cause, owner and action in every round on 6 of 7 scenarios.
  The exception was GS-12, which had a different result in each round.

## Limits

- **Small sample.** Seven scenarios and three rounds, so a difference of one run is noise. The holdout split wasn't run.
- **An outage, rerun.** Three runs in No cause guide's last round failed when the project's Anthropic API account ran
  out of credit. They weren't scored, and were rerun after the top-up on the same image and data.
- **One question, read by keywords.** The benchmark asks at most one question and reads the reply with keyword rules.
  Its authors expected it to hand back many cases without a clear reply, and it did on GS-01, GS-02 and GS-12.
- **How the benchmark's checks are counted.** After a merchant reply, the benchmark runs again from the top. Only its
  concluding pass is counted, so no check counts twice.

## Rerun

From the repository root, with the stack running and the images built:

```sh
uv run --project agent python -m agent.scripts.fixture_eval --reps 3   # everything; a rerun resumes
```

Results go to `agent/scripts/out/fixtures/` (git-ignored), where `summary.md` has the raw tables.

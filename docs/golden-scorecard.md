# Golden Dataset scorecard (B-05)

What the B-05 runner measured on the dev scenarios, the weakness it found and fixed, and what's still open. The
runner and its checks are described in [agent-graph.md](agent-graph.md#evaluation); the command is in
[agent/README.md](../agent/README.md#golden-dataset-evaluation-b-05).

**Setup.** Measured Nov 21-22, 2026 on `main` at `f8a7a3f` plus the B-05 changes, through the Compose stack:
- **Model:** `claude-opus-5-5` at medium effort, at most 12 steps and 2 merchant questions, Postgres checkpoints.
- **Prompt and schema:** prompt hash `35e47a9b38374288` before the fix and `07ec10f09253bdc9` after it, schema hash
  `2cc32ee62a7adecb`.
- **Dataset:** the dev split, GS-01 to GS-07, on seed 24 as of Nov 15, with answer-key hash `ba7188e4…` over the
  whole split. The rerun's `run.json` holds `7f659ef4…` instead, a hash over GS-07 alone, because its first session
  ran only GS-07. Every round reseeded Domain first.

## Results

| | Scenarios (runs) | Cause | Owner and action | Wrong guess | Abstained | Uncited diagnoses | Invalid citations | Key-evidence precision | Distractors handled | Cost | Mean time |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Fixed-rule baseline | 5 (5) | 1.00 | 1.00 | 0.00 | 0.00 | 0 | 0 | 0.98 | 0.09 | $0 | under 1 s |
| Agent before the fix | 5 (15) | 0.80 | 0.80 | 0.20 | 0.00 | 3 | 0 | 0.75 | 0.87 | $4.34 | 99 s |
| Agent after the fix (rerun) | 5 (7) | 0.80 | 0.80 | 0.20 | 0.00 | 0 | 0 | 0.92 | 0.87 | $2.25 | 107 s |

Each rate is averaged over a scenario's runs first, then over the five diagnosis scenarios with equal weight, so the
rerun's three GS-07 runs count once. With five scenarios, a 95% interval is wide (0.80 spans 38% to 96%), so read
the comparison as directional. An uncited diagnosis scores 0 key-evidence precision.

**Questions.** Before the fix, the agent asked the merchant in 0 of 3 GS-02 runs, the one scenario where B-05
judged a question needed, and in 6 of 12 runs where none was (every GS-01 and GS-06 run). After the fix, it asked
in 0 of 1 and 2 of 6. The baseline never asks.

**Per scenario, before the fix** (three runs each):

| Scenario | Cause and action | Notes |
|---|---|---|
| GS-01, POS modifier | 3/3 | Asked the merchant every time whether the modifier prints on tickets. |
| GS-02, packing | 3/3 | Never asked the merchant; high confidence in 2 of 3. |
| GS-05, inventory | 3/3 | |
| GS-06, Dasher handoff | 0/3 | Concluded `other` with an analyst handoff, and asked the merchant every time; see the first limitation. |
| GS-07, fraud cluster | 3/3 | Cited no supporting records, only the Nov 5 POS update as contradicting evidence; see AC3. |

The monitor opened no case for STORE-I or STORE-J (GS-03 and GS-04) in any round.

**What it shows.** On dev, the fixed rules match all five labels; the agent matches four, and GS-06 fails by
design. The agent explains distractors (0.87 against 0.09). It asks the merchant on GS-01 and GS-06, but never on
GS-02, the one scenario where B-05 judged a question needed. Both systems cite only valid records of the case's own
store.

## Workflow and safety

These ran once, with the agent before the fix, and weren't rerun after it.
- **STORE-B chain:** approve, recheck (not improved, case reopened), start without `reopen_of` refused with 409
  `CASE_NOT_STARTABLE`, `reopen_of` run completed, approve, recheck (improved, case closed), and a further
  `reopen_of` refused with 409 `REOPEN_NOT_ALLOWED`. Every step passed, and every dispatch followed an analyst
  approval.
- **Permission probes:** all 15 were denied as expected, and a before/after audit count showed they changed no
  approval or dispatch:
  - 401 without a token;
  - 403 for a viewer's writes and for the dispatch routes;
  - 404 or 403 for another store's analyst;
  - 422 for invalid input;
  - 404 from the gateway for the internal route;
  - 403 `SERVICE_TOKEN_INVALID` from Domain for evidence resolve, because the gateway strips `X-Service-Token`.
- **Release blockers:** none. No fabricated or other-store citation, and no approval bypass.

## AC3: one weakness, fixed and rerun

- **Weakness.** On GS-07, all three runs concluded `fraud_cluster`, two of them at high confidence, with no
  supporting evidence IDs. Rule G3 let a cause become supported once a matching check was linked, without a cited
  record, so the analyst had nothing to check against records.
- **Fix.** G3 now also needs at least one supporting evidence ID that isn't a merchant reply
  (`agent/app/graph/rules.py`), and one rejection lists both of G3's conditions when both fail. The prompt and the
  G3 rows in the docs say so, and a unit test covers it. The rerun below used the first version of the rule; the
  reply exclusion and the combined rejection came after it, from code review.
- **Rerun.**
  - **GS-07:** cited 3, 3 and 7 supporting records, with key-evidence precision 1.0, 1.0 and 0.86, and was still
    right every time. Key-evidence precision across the scenarios rose from 0.75 to 0.92.
  - **GS-01, GS-02 and GS-05:** one run each; all stayed right and cited evidence.
  - **GS-06:** its run concluded `packing` instead of `other`, again with an analyst handoff. In every earlier run
    `other` had seven supporting records, so the new rule didn't block it; this is most likely run-to-run variance
    from one run.

## Remaining limitations

- **GS-06 and rule G5 disagree.** The label expects a `dasher_handoff` diagnosis, which the agent can't support by
  design, because there's no Dasher data. The baseline's fixed rule gets it right from the claims alone. Relabeling
  GS-06 as unsure won't make the agent pass: an unsure label counts any diagnosis as a wrong guess, and the agent gave
  one in all four runs (the baseline's right answer would count as wrong too). A team decision is pending: keep the
  label and report GS-06 as a known miss, or relax G5, which changes the prompt.
- **W-01 wasn't exercised.** The agent never asked a question on STORE-K, so its no-reply path is covered only by
  offline tests and Domain's W-01 test.
- **Questions go to the wrong scenarios.** The agent didn't ask the merchant in any of its four GS-02 runs, though
  the label notes say confirmation is needed, and it asked in 8 of 18 runs where none was needed. "Needed" is a B-05
  judgment, not a label.
- **The set is small.** There are five diagnosis scenarios. The holdout (GS-08 to GS-10) runs once after the prompts
  are frozen.
- **The distractor map is hand-written** for the dev scenarios, so holdout distractors aren't scored until they're
  mapped.
- **Key-evidence precision** checks that cited records belong to the scenario's planted signal, not that each
  citation supports its claim.
- **The baseline's thresholds** were fixed before the run, but the dev scenarios are clear-cut. Mixed and misleading
  cases, in the holdout, are where fixed rules should break.
- **The costs leave out** the STORE-B chain's reopened run, about $0.30, and the first attempt of any turn that hit
  the output limit and was retried.

Raw results and traces are in `agent/scripts/out/golden/` (git-ignored), with an HTML report built from them by the
claude-api skill's report builder. Rerun the command, then the builder, to regenerate them. Each result's
investigation ID is its Langfuse session.

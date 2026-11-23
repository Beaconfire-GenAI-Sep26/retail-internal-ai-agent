// [10j] caseSteps — which boxes the case page shows, in one pure function
// ui-workflow.md v0.3 "Which box shows at each step", written as code so the
// components never look at status themselves. Two inputs drive it:
//   investigation_status (the latest run, Agent)  → boxes 5–12
//   case_status          (the whole case, Domain) → boxes 4, 13, 15
//
// v0.3's table covers steps 1–8 and Failed. Where a case ends is added here
// (d03 plan, Commit 2): unsure, analyst_review, closed, paused.
//
//   step              investigation      case_status          slot      also
//   1 Not started     —                  open                 —         Start
//   2 Agent checking  running            investigating        —         progress
//   3 Question        awaiting_approval  awaiting_decision    question  progress (paused)
//   4 Reply           awaiting_merchant  awaiting_merchant    reply     progress (paused), question history
//   5 Result          completed          awaiting_decision    result    recommendation
//   6 Action sent     completed          action_dispatched    result    recommendation, recheck
//   7 Not improved    completed          reopened             result    recommendation, recheck, Start new
//   8 Second run      running (reopen)   investigating        —         progress, previous run
//   failed            failed             open + last_error    error     Start again
//   unsure            unsure             analyst_review       result    (no recommendation)
//   analyst_review    completed          analyst_review       result    recommendation, recheck if one ran
//   closed / paused   completed          closed / paused      result    recommendation, recheck
//   no_run            — (agent lost it)  past open, or one   proposal  the latest action, no Start
//                                        pending proposal
//
// Whenever case_status is analyst_review (rejected action, unsure, second fix
// failed, or no_run), analysts also get "Mark as resolved" (showClose).
//
// Always true for every step: the previous run shows whenever this run is a
// reopen (reopen_of set), not only at step 8 — it stays through the second
// run's result, recheck and close.


// ═══════════════════════════════════════════════════════════════════
// 1. Helpers
// ═══════════════════════════════════════════════════════════════════
const START_LABELS = {
  first: 'Start investigation',
  reopen: 'Start new investigation',
  again: 'Start again',
};

// The recheck of this run's action, or null. Matched by proposal_id, not by
// position: contracts.md doesn't fix the order of CaseDetail.rechecks, and a
// reopened case has one recheck per run.
export const findRecheck = (investigation, caseDetail) => {
  const proposalId = investigation?.result?.proposal_id;
  if (!proposalId) return null;
  return caseDetail?.rechecks?.find((r) => r.proposal_id === proposalId) ?? null;
};

const hasRecheckFor = (investigation, caseDetail) => Boolean(findRecheck(investigation, caseDetail));

// This run's merchant questions (max 2 per run), oldest first.
// From CaseDetail.proposals; `latest` (proposals slice, by ID) wins when it has a
// newer copy, e.g. right after a decision, before the case reloads.
export const runQuestions = (investigation, caseDetail, latest = {}) =>
  (caseDetail?.proposals ?? [])
    .filter((p) => p.kind === 'merchant_question' && p.investigation_id === investigation?.investigation_id)
    .map((p) => latest[p.proposal_id] ?? p)
    .sort((a, b) => a.created_at.localeCompare(b.created_at));

// Decided (or replied) but the run hasn't continued: the decision call worked
// and the resume call didn't, or the page reloaded in between. Worked out from
// the data, not remembered in a component, so a reload still shows "Continue"
// (d03 plan, Commits 5–6).
//   awaiting_approval + the question is no longer pending
//   awaiting_merchant + a reply (or no_reply) is recorded for it   (reply from commit 6)
export const needsResume = (investigation, question, reply = null) => {
  if (!investigation || !question) return false;
  if (investigation.status === 'awaiting_approval') return question.status !== 'pending';
  if (investigation.status === 'awaiting_merchant') return Boolean(reply);
  return false;
};

// Everything hidden — each step turns on what it needs
const NOTHING = {
  step: null,
  slot: null, // the shared spot for boxes 6–10: 'question' | 'reply' | 'result' | 'error' | null
  showStart: false,
  startLabel: null,
  showProgress: false,
  pausedFor: null, // 'analyst' | 'merchant' while paused
  showTimeline: false, // CheckTimeline + HypothesisList
  showQuestionHistory: false, // read-only QuestionReview, if this run asked one
  showRecommendation: false, // RecommendationReview under the result
  showRecheck: false,
  showPrevious: false,
  proposalId: null, // slot 'proposal' only: the action to show when the agent has no run
  showClose: false, // "Mark as resolved": the case is in analyst_review
};


// check_id → its 1-based position in the timeline (oldest first), so the
// result can say "check 4" and link to it
export const checkNumbers = (checks = []) =>
  Object.fromEntries(checks.map((c, i) => [c.check_id, i + 1]));

// The challenge checks the leading cause survived, as check_ids.
// result.challenge_check_ids lists every challenge the run tried, including ones
// that didn't hold up. A challenge survived when it had enough data and matched
// if_true for the hypothesis it challenged (the agent's K2 rule, gate.py), and
// that hypothesis is the cause the result names.
export const survivedChallenges = (result, checks = [], hypotheses = []) => {
  const byId = Object.fromEntries(checks.map((c) => [c.check_id, c]));
  const causeOf = Object.fromEntries(hypotheses.map((h) => [h.hypothesis_id, h.cause_category]));
  return (result?.challenge_check_ids ?? []).filter((id) => {
    const check = byId[id];
    const target = check?.challenges;
    if (!target || !check.data_sufficient || check.matched?.[target] !== 'if_true') return false;
    // Hypothesis not in the list: trust the match rather than hide the check
    return !(target in causeOf) || causeOf[target] === result.cause_category;
  });
};

// The case's latest recommended action (intervention or handoff), or null
export const latestAction = (caseDetail) =>
  (caseDetail?.proposals ?? [])
    .filter((p) => p.kind === 'intervention' || p.kind === 'handoff')
    .reduce((latest, p) => (!latest || p.created_at > latest.created_at ? p : latest), null);

// Case statuses the agent starts a fresh run on (agent STARTABLE_STATUSES)
const STARTABLE = new Set(['open', 'investigating']);

// No run from the agent for this case. Either it was never investigated, or
// the agent restarted: it keeps runs in memory, so a case that already has a
// recommendation comes back with no run. Domain still has the proposals, so
// show the latest action (pending → decide it here) instead of a Start the
// agent would refuse (409 PROPOSAL_PENDING / CASE_NOT_STARTABLE).
const noRunView = (caseDetail) => {
  const hasPending = (caseDetail?.proposals ?? []).some((p) => p.status === 'pending');
  if (!caseDetail || (STARTABLE.has(caseDetail.status) && !hasPending)) {
    return { ...NOTHING, step: '1', showStart: true, startLabel: START_LABELS.first };
  }
  const action = latestAction(caseDetail);
  return {
    ...NOTHING,
    step: 'no_run',
    slot: action ? 'proposal' : null,
    showRecommendation: Boolean(action),
    proposalId: action?.proposal_id ?? null,
  };
};


// ═══════════════════════════════════════════════════════════════════
// 2. getCaseView({ investigation, caseDetail })
// ═══════════════════════════════════════════════════════════════════
// investigation: the latest InvestigationView, or null = never investigated
// caseDetail:    CaseDetail, or null while it loads
export const getCaseView = ({ investigation, caseDetail }) => ({
  ...runView({ investigation, caseDetail }),
  showClose: caseDetail?.status === 'analyst_review',
});

const runView = ({ investigation, caseDetail }) => {
  // Step 1 (never investigated), or the agent lost the run (no_run)
  if (!investigation) return noRunView(caseDetail);

  const isReopen = Boolean(investigation.reopen_of);
  const base = {
    ...NOTHING,
    showTimeline: true,
    showPrevious: isReopen,
  };

  switch (investigation.status) {
    // Steps 2 and 8: the agent is checking
    case 'running':
      return { ...base, step: isReopen ? '8' : '2', showProgress: true, showQuestionHistory: true };

    // Step 3: a question waits for an analyst
    case 'awaiting_approval':
      return { ...base, step: '3', slot: 'question', showProgress: true, pausedFor: 'analyst' };

    // Step 4: the question was sent, waiting for the merchant
    case 'awaiting_merchant':
      return {
        ...base,
        step: '4',
        slot: 'reply',
        showProgress: true,
        pausedFor: 'merchant',
        showQuestionHistory: true,
      };

    // Run failed: error + Start again. Checks show only if the run got that far.
    case 'failed': {
      const hasChecks = (investigation.checks?.length ?? 0) > 0 || (investigation.hypotheses?.length ?? 0) > 0;
      return {
        ...base,
        step: 'failed',
        slot: 'error',
        showTimeline: hasChecks,
        showStart: true,
        startLabel: START_LABELS.again,
      };
    }

    // No cause confirmed: result in its unsure layout, no recommendation
    case 'unsure':
      return { ...base, step: 'unsure', slot: 'result', showQuestionHistory: true };

    // Completed: what shows next depends on where the case went after the decision
    case 'completed':
      return completedView(base, investigation, caseDetail);

    // A status this UI doesn't know yet: show what the agent reported, no actions
    default:
      return { ...base, step: null };
  }
};

// Steps 5, 6, 7 and the ends that follow a diagnosis
const completedView = (base, investigation, caseDetail) => {
  const view = { ...base, slot: 'result', showRecommendation: true, showQuestionHistory: true };

  switch (caseDetail?.status) {
    case 'action_dispatched':
      return { ...view, step: '6', showRecheck: true };
    case 'reopened':
      return { ...view, step: '7', showRecheck: true, showStart: true, startLabel: START_LABELS.reopen };
    case 'closed':
      return { ...view, step: 'closed', showRecheck: true };
    case 'paused':
      return { ...view, step: 'paused', showRecheck: true };
    // Action rejected (no recheck), or the second fix also failed (recheck ran)
    case 'analyst_review':
      return { ...view, step: 'analyst_review', showRecheck: hasRecheckFor(investigation, caseDetail) };
    // awaiting_decision, or the case is still loading
    default:
      return { ...view, step: '5' };
  }
};

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
};


// check_id → its 1-based position in the timeline (oldest first), so the
// result can say "check 4" and link to it
export const checkNumbers = (checks = []) =>
  Object.fromEntries(checks.map((c, i) => [c.check_id, i + 1]));


// ═══════════════════════════════════════════════════════════════════
// 2. getCaseView({ investigation, caseDetail })
// ═══════════════════════════════════════════════════════════════════
// investigation: the latest InvestigationView, or null = never investigated
// caseDetail:    CaseDetail, or null while it loads
export const getCaseView = ({ investigation, caseDetail }) => {
  // Step 1: never investigated
  if (!investigation) {
    return { ...NOTHING, step: '1', showStart: true, startLabel: START_LABELS.first };
  }

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

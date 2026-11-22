// [10y] caseStages — the case's progress as 5 stages, and what the analyst should do next
// Pure functions on data the page already has (getCaseView + CaseDetail): no
// API call. CaseStepper draws the stages; NextActionBanner shows the next action.
//
//   Detected ─ Investigated ─ Decide action ─ Action sent ─ Recheck
//     done        done          now (you)       todo         todo      ← step 5
//
// getCaseView's step (caseSteps.js) picks the current stage. With no run from
// the agent (step 'no_run', or the agent couldn't be reached) the case status
// picks it instead.


// ═══════════════════════════════════════════════════════════════════
// 1. Imports
// ═══════════════════════════════════════════════════════════════════
import { findRecheck, latestAction } from './caseSteps';
import { formatDate, labelOf, RECHECK_STATUS_LABELS } from '../../api/format';


// ═══════════════════════════════════════════════════════════════════
// 2. Stages and where each step sits
// ═══════════════════════════════════════════════════════════════════
export const STAGES = [
  { key: 'detected', label: 'Detected' },
  { key: 'investigated', label: 'Investigated' },
  { key: 'decide', label: 'Decide action' },
  { key: 'sent', label: 'Action sent' },
  { key: 'recheck', label: 'Recheck' },
];

// getCaseView step → current stage. null = every stage is done (closed).
const STAGE_BY_STEP = {
  1: 'investigated',
  2: 'investigated',
  3: 'investigated',
  4: 'investigated',
  8: 'investigated',
  failed: 'investigated',
  5: 'decide',
  unsure: 'decide',
  analyst_review: 'decide',
  6: 'recheck',
  7: 'recheck',
  paused: 'recheck',
  closed: null,
};

// No run to go by: the case status (Domain) → current stage
const STAGE_BY_CASE_STATUS = {
  open: 'investigated',
  investigating: 'investigated',
  awaiting_merchant: 'investigated',
  awaiting_decision: 'decide',
  analyst_review: 'decide',
  action_dispatched: 'recheck',
  reopened: 'recheck',
  paused: 'recheck',
  closed: null,
};

// Steps where the case waits for the analyst (red), not for the agent or the merchant
const NEEDS_ANALYST = new Set(['1', '3', '4', '5', '7', 'failed']);

// The stage text under "Investigated" while it is the current stage
const INVESTIGATING_NOTES = {
  1: 'Not started',
  2: 'Agent checking',
  8: 'Agent checking again',
  3: 'Question waits for you',
  4: 'Waiting on the merchant',
  failed: 'Stopped',
};

const plural = (n, word) => `${n} ${word}${n === 1 ? '' : 's'}`;

// A pending action with no run from the agent (it restarted): still decided here
const pendingAction = (caseDetail) => latestAction(caseDetail)?.status === 'pending';

const currentStageOf = (view, caseDetail) => {
  if (view?.step && view.step !== 'no_run' && view.step in STAGE_BY_STEP) return STAGE_BY_STEP[view.step];
  const status = caseDetail?.status;
  return status in STAGE_BY_CASE_STATUS ? STAGE_BY_CASE_STATUS[status] : 'investigated';
};


// ═══════════════════════════════════════════════════════════════════
// 3. getCaseStages({ view, investigation, caseDetail })
// ═══════════════════════════════════════════════════════════════════
// view: getCaseView(...) or null when the agent couldn't be reached
// → [{ key, label, state: 'done' | 'now' | 'todo', attention, note }]
//   attention: true on the current stage when the analyst has to act
export const getCaseStages = ({ view, investigation, caseDetail }) => {
  const tz = caseDetail?.store?.timezone;
  const current = currentStageOf(view, caseDetail);
  const currentIndex = current == null ? STAGES.length : STAGES.findIndex((s) => s.key === current);
  const step = view?.step;
  const action = latestAction(caseDetail);
  const recheck = findRecheck(investigation, caseDetail)
    ?? (caseDetail?.rechecks ?? []).find((r) => r.proposal_id === action?.proposal_id) ?? null;
  const questions = (caseDetail?.proposals ?? []).filter(
    (p) => p.kind === 'merchant_question' && p.investigation_id === investigation?.investigation_id,
  ).length;

  const notes = {
    detected: caseDetail?.opened_at ? formatDate(caseDetail.opened_at, tz) : '',
    investigated: investigation
      ? [plural(investigation.checks?.length ?? 0, 'check'), questions && plural(questions, 'question')].filter(Boolean).join(' · ')
      : '',
    decide: action?.decided_at ? `${action.status === 'approved' ? 'Approved' : 'Rejected'} ${formatDate(action.decided_at, tz)}` : '',
    sent: action?.dispatch ? formatDate(action.dispatch.dispatched_at, tz) : '',
    recheck: recheck
      ? (recheck.status === 'scheduled' ? `Due ${formatDate(recheck.scheduled_for, tz)}` : labelOf(RECHECK_STATUS_LABELS, recheck.status))
      : (action ? `${action.content?.recheck_after_days} days after sent` : ''),
  };

  // The current stage says what is happening now instead
  const nowNotes = {
    investigated: INVESTIGATING_NOTES[step] ?? 'In progress',
    decide: step === 'unsure' || step === 'analyst_review' ? 'Analyst review' : 'Waiting on you',
  };

  const attention = NEEDS_ANALYST.has(step) || (step === 'no_run' && pendingAction(caseDetail));

  return STAGES.map((stage, i) => {
    let state = 'todo';
    if (i < currentIndex) state = 'done';
    if (i === currentIndex) state = 'now';
    const note = state === 'now' && nowNotes[stage.key] ? nowNotes[stage.key] : notes[stage.key];
    return { ...stage, state, attention: state === 'now' && attention, note: note || '—' };
  });
};


// ═══════════════════════════════════════════════════════════════════
// 4. getNextAction({ view, caseDetail, isAnalyst })
// ═══════════════════════════════════════════════════════════════════
// The one thing the analyst should do now, for the banner at the top of the
// page, or null (nothing to do, the agent is working, or a viewer is signed in).
// → { title, text, cta }
const NEXT_ACTIONS = {
  1: {
    title: 'Start the investigation',
    text: "The agent checks this store's data and looks for the cause of the spike.",
    cta: 'Go to start',
  },
  3: {
    title: 'Your decision is needed',
    text: 'The agent wants to ask the merchant a question. Nothing is sent until you approve it.',
    cta: 'Review question',
  },
  4: {
    title: "Record the merchant's reply",
    text: 'The question was sent. Enter the reply, or "no reply", so the agent can continue.',
    cta: 'Record reply',
  },
  5: {
    title: 'Your decision is needed',
    text: 'The agent recommends an action. Nothing is sent until you approve it.',
    cta: 'Review action',
  },
  7: {
    title: "The fix didn't work",
    text: 'The recheck found no improvement. Start a new investigation.',
    cta: 'Start again',
  },
  failed: {
    title: 'The investigation stopped',
    text: 'The agent could not finish. See what went wrong and start it again.',
    cta: 'See error',
  },
};

export const getNextAction = ({ view, caseDetail, isAnalyst }) => {
  if (!isAnalyst || !view) return null;
  if (view.step === 'no_run' && pendingAction(caseDetail)) return NEXT_ACTIONS[5];
  return NEXT_ACTIONS[view.step] ?? null;
};

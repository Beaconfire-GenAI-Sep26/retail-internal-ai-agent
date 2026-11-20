// getCaseView: every step of ui-workflow.md v0.3, Failed, Unsure, and the case
// ends the d03 plan added (analyst_review, closed, paused).
import { describe, expect, it } from 'vitest';
import { getCaseView, findRecheck } from './caseSteps';

const inv = (status, extra = {}) => ({
  investigation_id: 'INV-2',
  status,
  reopen_of: null,
  checks: [{ check_id: 'CHK-1' }],
  hypotheses: [{ hypothesis_id: 'HYP-1' }],
  result: status === 'completed' ? { outcome: 'diagnosis', proposal_id: 'PROP-0001' } : null,
  ...extra,
});
const caseIn = (status, extra = {}) => ({ case_id: 'CASE-0001', status, rechecks: [], ...extra });
const view = (investigation, caseDetail) => getCaseView({ investigation, caseDetail });

describe('steps 1–8', () => {
  it('1 not started: Start investigation only', () => {
    const v = view(null, caseIn('open'));
    expect(v).toMatchObject({ step: '1', showStart: true, startLabel: 'Start investigation', showTimeline: false, slot: null });
  });

  it('2 agent checking: progress + timeline, no slot', () => {
    expect(view(inv('running'), caseIn('investigating')))
      .toMatchObject({ step: '2', showProgress: true, pausedFor: null, showTimeline: true, slot: null, showStart: false, showPrevious: false });
  });

  it('3 question to approve: question slot, paused for the analyst', () => {
    expect(view(inv('awaiting_approval'), caseIn('awaiting_decision')))
      .toMatchObject({ step: '3', slot: 'question', showProgress: true, pausedFor: 'analyst', showQuestionHistory: false });
  });

  it('4 waiting for the reply: reply slot, paused for the merchant, question as history', () => {
    expect(view(inv('awaiting_merchant'), caseIn('awaiting_merchant')))
      .toMatchObject({ step: '4', slot: 'reply', pausedFor: 'merchant', showQuestionHistory: true });
  });

  it('5 result and action: result + recommendation, no recheck yet', () => {
    expect(view(inv('completed'), caseIn('awaiting_decision')))
      .toMatchObject({ step: '5', slot: 'result', showRecommendation: true, showRecheck: false, showProgress: false, showStart: false });
  });

  it('6 action sent: recheck card appears', () => {
    expect(view(inv('completed'), caseIn('action_dispatched')))
      .toMatchObject({ step: '6', slot: 'result', showRecommendation: true, showRecheck: true, showStart: false });
  });

  it('7 not improved: recheck stays, Start new investigation comes back', () => {
    expect(view(inv('completed'), caseIn('reopened')))
      .toMatchObject({ step: '7', showRecheck: true, showStart: true, startLabel: 'Start new investigation' });
  });

  it('8 second investigation: progress + the previous run', () => {
    expect(view(inv('running', { reopen_of: 'INV-1' }), caseIn('investigating')))
      .toMatchObject({ step: '8', showProgress: true, showPrevious: true });
  });
});

describe('failed', () => {
  it('error slot + Start again; checks show when the run got that far', () => {
    expect(view(inv('failed'), caseIn('open', { last_error: 'RUN_TIMEOUT' })))
      .toMatchObject({ step: 'failed', slot: 'error', showStart: true, startLabel: 'Start again', showTimeline: true });
  });

  it('no checks yet → no timeline', () => {
    expect(view(inv('failed', { checks: [], hypotheses: [] }), caseIn('open')).showTimeline).toBe(false);
  });

  it('a failed second run still shows the previous run', () => {
    expect(view(inv('failed', { reopen_of: 'INV-1' }), caseIn('open')).showPrevious).toBe(true);
  });
});

describe('unsure', () => {
  it('result slot, no recommendation, question kept as history', () => {
    expect(view(inv('unsure'), caseIn('analyst_review')))
      .toMatchObject({ step: 'unsure', slot: 'result', showRecommendation: false, showQuestionHistory: true, showStart: false });
  });
});

describe('where a case ends after a diagnosis', () => {
  it('action rejected → analyst review, no recheck', () => {
    expect(view(inv('completed'), caseIn('analyst_review')))
      .toMatchObject({ step: 'analyst_review', showRecommendation: true, showRecheck: false });
  });

  it('second fix also failed → analyst review with the recheck result', () => {
    const c = caseIn('analyst_review', { rechecks: [{ recheck_id: 'RCK-0002', proposal_id: 'PROP-0001' }] });
    expect(view(inv('completed', { reopen_of: 'INV-1' }), c))
      .toMatchObject({ step: 'analyst_review', showRecheck: true, showPrevious: true });
  });

  it('a recheck for another run does not count', () => {
    const c = caseIn('analyst_review', { rechecks: [{ recheck_id: 'RCK-0001', proposal_id: 'PROP-0009' }] });
    expect(view(inv('completed'), c).showRecheck).toBe(false);
  });

  it('closed → result, action and recheck stay', () => {
    expect(view(inv('completed'), caseIn('closed')))
      .toMatchObject({ step: 'closed', showRecommendation: true, showRecheck: true, showStart: false });
  });

  it('paused (not enough data) → same, no Start', () => {
    expect(view(inv('completed'), caseIn('paused')))
      .toMatchObject({ step: 'paused', showRecheck: true, showStart: false });
  });

  it('second run closed → the previous run is still shown', () => {
    expect(view(inv('completed', { reopen_of: 'INV-1' }), caseIn('closed')).showPrevious).toBe(true);
  });

  it('case still loading → treated as step 5', () => {
    expect(view(inv('completed'), null).step).toBe('5');
  });
});

describe('findRecheck', () => {
  it("picks this run's recheck by proposal_id, whatever the order", () => {
    const c = caseIn('closed', { rechecks: [
      { recheck_id: 'RCK-0002', proposal_id: 'PROP-0001' },
      { recheck_id: 'RCK-0001', proposal_id: 'PROP-0009' },
    ] });
    expect(findRecheck(inv('completed'), c).recheck_id).toBe('RCK-0002');
  });

  it('no action yet, or not scheduled yet → null', () => {
    expect(findRecheck(inv('unsure'), caseIn('analyst_review'))).toBeNull();
    expect(findRecheck(inv('completed'), caseIn('awaiting_decision'))).toBeNull();
  });
});

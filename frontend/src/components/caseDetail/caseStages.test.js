// getCaseStages / getNextAction: the stepper and the banner for each step
import { describe, expect, it } from 'vitest';
import { getCaseView } from './caseSteps';
import { getCaseStages, getNextAction } from './caseStages';

const TZ = 'America/Chicago';
const inv = (status, extra = {}) => ({
  investigation_id: 'INV-2',
  status,
  reopen_of: null,
  checks: [{ check_id: 'CHK-1' }, { check_id: 'CHK-2' }],
  hypotheses: [],
  result: status === 'completed' ? { outcome: 'diagnosis', proposal_id: 'PROP-0001' } : null,
  ...extra,
});
const action = (extra = {}) => ({
  proposal_id: 'PROP-0001',
  kind: 'intervention',
  investigation_id: 'INV-2',
  status: 'pending',
  created_at: '2026-11-16T21:40:00Z',
  decided_at: null,
  dispatch: null,
  content: { recheck_after_days: 14 },
  ...extra,
});
const caseIn = (status, extra = {}) => ({
  case_id: 'CASE-0001',
  status,
  opened_at: '2026-11-16T05:59:00Z',
  store: { timezone: TZ },
  proposals: [],
  rechecks: [],
  ...extra,
});
const stages = (investigation, caseDetail) =>
  getCaseStages({ view: getCaseView({ investigation, caseDetail }), investigation, caseDetail });
const states = (list) => list.map((s) => s.state + (s.attention ? '!' : '')).join(' ');

describe('getCaseStages', () => {
  it('step 1: detected done, investigation is next and waits for the analyst', () => {
    const list = stages(null, caseIn('open'));
    expect(states(list)).toBe('done now! todo todo todo');
    expect(list[0].note).toBe('Nov 15, 2026'); // opened_at in the store's timezone
    expect(list[1].note).toBe('Not started');
  });

  it('step 2: the agent is checking — current, but not the analyst\'s turn', () => {
    const list = stages(inv('running'), caseIn('investigating'));
    expect(states(list)).toBe('done now todo todo todo');
    expect(list[1].note).toBe('Agent checking');
  });

  it('step 4: waiting on the merchant still asks the analyst to record the reply', () => {
    expect(states(stages(inv('awaiting_merchant'), caseIn('awaiting_merchant')))).toBe('done now! todo todo todo');
  });

  it('step 5: investigation done with its counts, decision waits on you', () => {
    const caseDetail = caseIn('awaiting_decision', {
      proposals: [action(), { proposal_id: 'PROP-0002', kind: 'merchant_question', investigation_id: 'INV-2' }],
    });
    const list = stages(inv('completed'), caseDetail);
    expect(states(list)).toBe('done done now! todo todo');
    expect(list[1].note).toBe('2 checks · 1 question');
    expect(list[2].note).toBe('Waiting on you');
    expect(list[4].note).toBe('14 days after sent');
  });

  it('step 6: action sent with its date, recheck due', () => {
    const caseDetail = caseIn('action_dispatched', {
      proposals: [action({ status: 'approved', decided_at: '2026-11-17T15:00:00Z', dispatch: { dispatched_at: '2026-11-17T15:00:01Z' } })],
      rechecks: [{ proposal_id: 'PROP-0001', status: 'scheduled', scheduled_for: '2026-12-01T15:00:00Z' }],
    });
    const list = stages(inv('completed'), caseDetail);
    expect(states(list)).toBe('done done done done now');
    expect(list[2].note).toBe('Approved Nov 17, 2026');
    expect(list[3].note).toBe('Nov 17, 2026');
    expect(list[4].note).toBe('Due Dec 1, 2026');
  });

  it('closed: every stage done', () => {
    expect(states(stages(inv('completed'), caseIn('closed')))).toBe('done done done done done');
  });

  it('unsure: decision stage shows analyst review, not "waiting on you"', () => {
    const list = stages(inv('unsure'), caseIn('analyst_review'));
    expect(states(list)).toBe('done done now todo todo');
    expect(list[2].note).toBe('Analyst review');
  });

  it('no run from the agent: the case status picks the stage; a pending action still needs you', () => {
    const list = stages(null, caseIn('awaiting_decision', { proposals: [action()] }));
    expect(states(list)).toBe('done done now! todo todo');
  });

  it('agent unreachable (no view): falls back to the case status', () => {
    const caseDetail = caseIn('action_dispatched');
    expect(states(getCaseStages({ view: null, investigation: null, caseDetail }))).toBe('done done done done now');
  });

  it('empty notes show a dash', () => {
    const list = stages(null, caseIn('open'));
    expect(list[3].note).toBe('—');
  });
});

describe('getNextAction', () => {
  const next = (investigation, caseDetail, isAnalyst = true) =>
    getNextAction({ view: getCaseView({ investigation, caseDetail }), caseDetail, isAnalyst });

  it('asks for a decision at steps 3 and 5', () => {
    expect(next(inv('awaiting_approval'), caseIn('awaiting_decision'))).toMatchObject({ cta: 'Review question' });
    expect(next(inv('completed'), caseIn('awaiting_decision'))).toMatchObject({ cta: 'Review action', target: 'decide' });
  });

  it('step 4: confirm the reply that shows up live (D-05)', () => {
    expect(next(inv('awaiting_merchant'), caseIn('awaiting_merchant'))).toMatchObject({ cta: 'Go to reply' });
  });

  it('step 7: jumps to the recheck, where Start new investigation sits (D-05)', () => {
    expect(next(inv('completed'), caseIn('reopened'))).toMatchObject({ cta: 'Start again', target: 'recheck' });
  });

  it('analyst review: close the case with Mark as resolved (D-05)', () => {
    expect(next(inv('completed'), caseIn('analyst_review'))).toMatchObject({ cta: 'Mark as resolved', target: 'followup' });
    expect(next(inv('unsure'), caseIn('analyst_review'))).toMatchObject({ target: 'followup' });
    expect(next(null, caseIn('analyst_review'))).toMatchObject({ target: 'followup' });
  });

  it('nothing while the agent works or after the action is sent', () => {
    expect(next(inv('running'), caseIn('investigating'))).toBeNull();
    expect(next(inv('completed'), caseIn('action_dispatched'))).toBeNull();
  });

  it('a viewer never gets the banner', () => {
    expect(next(inv('completed'), caseIn('awaiting_decision'), false)).toBeNull();
  });

  it('no run but a pending action: still review the action', () => {
    expect(next(null, caseIn('awaiting_decision', { proposals: [action()] }))).toMatchObject({ cta: 'Review action' });
  });

  it('no view (agent unreachable): nothing', () => {
    expect(getNextAction({ view: null, caseDetail: caseIn('open'), isAnalyst: true })).toBeNull();
  });
});

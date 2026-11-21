// getCaseView: every step of ui-workflow.md v0.3, Failed, Unsure, and the case
// ends the d03 plan added (analyst_review, closed, paused).
import { describe, expect, it } from 'vitest';
import { getCaseView, findRecheck, runQuestions, needsResume, survivedChallenges, latestAction } from './caseSteps';

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

describe('runQuestions', () => {
  const q = (id, invId, created_at, status = 'pending') => ({ proposal_id: id, kind: 'merchant_question', investigation_id: invId, created_at, status });
  const c = caseIn('awaiting_merchant', { proposals: [
    q('PROP-0004', 'INV-2', '2026-11-16T15:10:00Z'),
    q('PROP-0002', 'INV-2', '2026-11-16T15:04:00Z'),
    q('PROP-0001', 'INV-1', '2026-11-01T10:00:00Z'),
    { proposal_id: 'PROP-0003', kind: 'intervention', investigation_id: 'INV-2', created_at: '2026-11-16T15:20:00Z' },
  ] });

  it("only this run's questions, oldest first", () => {
    expect(runQuestions(inv('running'), c).map((p) => p.proposal_id)).toEqual(['PROP-0002', 'PROP-0004']);
  });

  it('a newer copy from the proposals slice wins', () => {
    const latest = { 'PROP-0002': { ...c.proposals[1], status: 'approved' } };
    expect(runQuestions(inv('running'), c, latest)[0].status).toBe('approved');
  });
});

describe('needsResume', () => {
  const question = (status) => ({ proposal_id: 'PROP-0002', status });

  it('question decided while the run still waits for approval → Continue', () => {
    expect(needsResume(inv('awaiting_approval'), question('approved'))).toBe(true);
    expect(needsResume(inv('awaiting_approval'), question('rejected'))).toBe(true);
  });

  it('question still pending → no', () => {
    expect(needsResume(inv('awaiting_approval'), question('pending'))).toBe(false);
  });

  it('waiting for the merchant: only once a reply is recorded', () => {
    expect(needsResume(inv('awaiting_merchant'), question('approved'))).toBe(false);
    expect(needsResume(inv('awaiting_merchant'), question('approved'), { outcome: 'no_reply' })).toBe(true);
  });

  it('a running or finished run never needs it', () => {
    expect(needsResume(inv('running'), question('approved'))).toBe(false);
    expect(needsResume(inv('completed'), question('approved'), { outcome: 'replied' })).toBe(false);
  });
});

describe('no run from the agent (it restarted)', () => {
  const action = (id, status, created_at, extra = {}) =>
    ({ proposal_id: id, kind: 'intervention', status, created_at, investigation_id: 'INV-1', ...extra });

  it('open with no proposal: Start investigation', () => {
    expect(view(null, caseIn('open', { proposals: [] }))).toMatchObject({ step: '1', showStart: true });
  });

  it('investigating with no run (lost mid-run): Start investigation', () => {
    expect(view(null, caseIn('investigating', { proposals: [] }))).toMatchObject({ step: '1', showStart: true });
  });

  it('pending action: show it to decide, no Start', () => {
    const v = view(null, caseIn('awaiting_decision', { proposals: [action('PROP-0001', 'pending', '2026-11-16T15:00:00Z')] }));
    expect(v).toMatchObject({ step: 'no_run', slot: 'proposal', proposalId: 'PROP-0001', showRecommendation: true, showStart: false });
  });

  it('pending action on an investigating case: still no Start (agent refuses PROPOSAL_PENDING)', () => {
    const v = view(null, caseIn('investigating', { proposals: [action('PROP-0001', 'pending', '2026-11-16T15:00:00Z')] }));
    expect(v).toMatchObject({ step: 'no_run', proposalId: 'PROP-0001', showStart: false });
  });

  it('decided case: the latest action, read-only, no Start', () => {
    const v = view(null, caseIn('action_dispatched', {
      proposals: [
        action('PROP-0001', 'approved', '2026-11-16T15:00:00Z'),
        action('PROP-0003', 'approved', '2026-11-18T15:00:00Z', { kind: 'handoff' }),
        { proposal_id: 'PROP-0002', kind: 'merchant_question', status: 'approved', created_at: '2026-11-19T15:00:00Z' },
      ],
    }));
    expect(v).toMatchObject({ step: 'no_run', slot: 'proposal', proposalId: 'PROP-0003', showStart: false });
  });

  it('past open with no action: message only', () => {
    expect(view(null, caseIn('reopened', { proposals: [] })))
      .toMatchObject({ step: 'no_run', slot: null, proposalId: null, showStart: false });
  });

  it('latestAction skips merchant questions', () => {
    expect(latestAction({ proposals: [{ proposal_id: 'Q', kind: 'merchant_question', created_at: 'z' }] })).toBeNull();
  });
});

describe('survivedChallenges', () => {
  const hypotheses = [
    { hypothesis_id: 'H-POS', cause_category: 'pos_modifier_mapping' },
    { hypothesis_id: 'H-PACK', cause_category: 'packing' },
  ];
  const challenge = (id, target, outcome, extra = {}) =>
    ({ check_id: id, kind: 'challenge', challenges: target, matched: { [target]: outcome }, data_sufficient: true, ...extra });
  const result = (ids) => ({ outcome: 'diagnosis', cause_category: 'pos_modifier_mapping', challenge_check_ids: ids });

  it('keeps only challenges on the named cause that matched if_true with enough data', () => {
    const checks = [
      challenge('C1', 'H-POS', 'if_true'),
      challenge('C2', 'H-POS', 'if_false'),
      challenge('C3', 'H-POS', 'neither'),
      challenge('C4', 'H-POS', 'if_true', { data_sufficient: false }),
      challenge('C5', 'H-PACK', 'if_true'),
    ];
    expect(survivedChallenges(result(['C1', 'C2', 'C3', 'C4', 'C5']), checks, hypotheses)).toEqual(['C1']);
  });

  it('unknown check or hypothesis: drops the check, trusts the match', () => {
    const checks = [challenge('C1', 'H-OTHER', 'if_true')];
    expect(survivedChallenges(result(['C1', 'MISSING']), checks, hypotheses)).toEqual(['C1']);
  });
});

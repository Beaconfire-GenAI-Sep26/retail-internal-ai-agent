// Walks every path of ui-workflow.md v0.3 through the mock endpoints,
// checking investigation_status and case_status at each step.
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import * as m from './mockInvestigations';
import { EVIDENCE, SAMPLE_REPLY_TEXT } from './fixtures';

const analyst = { user_id: 'USR-001', role: 'loe_analyst', store_ids: ['STORE-A', 'STORE-B'] };
const viewer = { user_id: 'USR-002', role: 'viewer', store_ids: ['STORE-A'] };
const ctx = { user: analyst };

// Mock endpoints wait with setTimeout; run them on fake timers
const call = async (fn, ...args) => {
  const p = fn(...args);
  p.catch(() => {}); // a rejection is read below; don't flag it as unhandled meanwhile
  await vi.runAllTimersAsync();
  return p;
};
const fail = async (fn, ...args) => {
  try {
    await call(fn, ...args);
  } catch (err) {
    return err.response;
  }
  throw new Error('expected an error');
};

const realCase = (case_id) => ({ case_id, status: 'open', last_error: null, reopen_count: 0, investigation_ids: [], proposals: [], rechecks: [] });
const caseStatus = (case_id) => m.applyMockCase(realCase(case_id)).status;

// Poll until the run leaves `running`
const pollToRest = async (id) => {
  let view;
  for (let i = 0; i < 20; i += 1) {
    view = await call(m.mockGetInvestigation, id, ctx);
    if (view.status !== 'running') return view;
  }
  throw new Error('still running');
};

const decide = (proposal, decision, key = crypto.randomUUID()) =>
  call(m.mockDecideProposal, proposal.proposal_id, { version: proposal.version, decision, note: null }, { ...ctx, idempotencyKey: key });

const resume = (id) => call(m.mockResumeInvestigation, id, { ...ctx, idempotencyKey: crypto.randomUUID() });

// Runs CASE-0002 to step 5: start → question approved → reply → completed
const packingToResult = async () => {
  const start = await call(m.mockStartInvestigation, { case_id: 'CASE-0002', reopen_of: null }, ctx);
  const paused = await pollToRest(start.investigation_id);
  const question = await call(m.mockGetProposal, paused.pending_proposal_id, ctx);
  await decide(question, 'approve');
  await resume(start.investigation_id);
  await call(m.mockRecordReply, question.proposal_id, { outcome: 'replied', text: SAMPLE_REPLY_TEXT }, { ...ctx, idempotencyKey: 'r1' });
  await resume(start.investigation_id);
  const done = await pollToRest(start.investigation_id);
  return { inv: done, question };
};

beforeEach(() => {
  vi.useFakeTimers();
  m.resetMocks();
});
afterEach(() => vi.useRealTimers());

describe('CASE-0002 full loop: question → reply → action → not improved → reopen → inventory → closed', () => {
  it('follows the v0.3 statuses step by step', async () => {
    // Step 1 → 2
    const start = await call(m.mockStartInvestigation, { case_id: 'CASE-0002', reopen_of: null }, ctx);
    expect(start.status).toBe('running');
    expect(caseStatus('CASE-0002')).toBe('investigating');

    // Step 3: question to approve
    const paused = await pollToRest(start.investigation_id);
    expect(paused.status).toBe('awaiting_approval');
    expect(paused.checks).toHaveLength(7);
    expect(caseStatus('CASE-0002')).toBe('awaiting_decision');

    const question = await call(m.mockGetProposal, paused.pending_proposal_id, ctx);
    expect(question.kind).toBe('merchant_question');

    // Edit → version 2; deciding v1 is stale
    const edited = await call(m.mockEditProposal, question.proposal_id, { content: { ...question.content, question_text: 'Edited?' } }, ctx);
    expect(edited.version).toBe(2);
    expect((await fail(decide, question, 'approve')).data.error.code).toBe('STALE_VERSION');

    // Step 4: approve (+ same key again → no second dispatch) + resume
    const approved = await decide(edited, 'approve', 'k-approve');
    const again = await decide(edited, 'approve', 'k-approve');
    expect(again.dispatch.dispatch_id).toBe(approved.dispatch.dispatch_id);
    expect(caseStatus('CASE-0002')).toBe('awaiting_merchant');
    const waiting = await resume(start.investigation_id);
    expect(waiting.status).toBe('awaiting_merchant');
    expect(waiting.pending_proposal_id).toBe(question.proposal_id);

    // Reply + resume → running → completed (step 5)
    const reply = await call(m.mockRecordReply, question.proposal_id, { outcome: 'replied', text: SAMPLE_REPLY_TEXT }, { ...ctx, idempotencyKey: 'r1' });
    expect((await fail(m.mockRecordReply, question.proposal_id, { outcome: 'no_reply' }, { ...ctx, idempotencyKey: 'r2' })).data.error.code).toBe('REPLY_EXISTS');
    expect((await resume(start.investigation_id)).status).toBe('running');
    expect(caseStatus('CASE-0002')).toBe('investigating');
    const done = await pollToRest(start.investigation_id);
    expect(done.status).toBe('completed');
    expect(done.result.supporting_evidence_ids).toContain(reply.evidence_id);
    expect(caseStatus('CASE-0002')).toBe('awaiting_decision');

    // Reply shows up as evidence
    const ev = await call(m.mockGetEvidence, reply.evidence_id, ctx);
    expect(ev.type).toBe('merchant_reply');
    expect(ev.attributes.text).toBe(SAMPLE_REPLY_TEXT);

    // Step 6: approve the action → dispatched + recheck scheduled
    const action = await call(m.mockGetProposal, done.result.proposal_id, ctx);
    expect(action.content.action_id).toBe('add_large_order_bag_check');
    const sent = await decide(action, 'approve');
    expect(sent.dispatch.channel).toBe('mock_team_queue');
    let detail = m.applyMockCase(realCase('CASE-0002'));
    expect(detail.status).toBe('action_dispatched');
    expect(detail.rechecks).toHaveLength(1);
    expect(detail.rechecks[0].status).toBe('scheduled');
    expect(detail.proposals.map((p) => p.proposal_id)).toEqual([question.proposal_id, action.proposal_id]);

    // Step 7: run recheck → not improved → reopened
    const rck = await call(m.mockRunRecheck, detail.rechecks[0].recheck_id, { ...ctx, idempotencyKey: 'rc1' });
    expect(rck.status).toBe('not_improved');
    expect(rck.after.rate).toBeCloseTo(26 / 193, 4);
    expect(rck.control).not.toBeNull();
    expect((await fail(m.mockRunRecheck, rck.recheck_id, { ...ctx, idempotencyKey: 'rc2' })).data.error.code).toBe('RECHECK_ALREADY_RUN');
    detail = m.applyMockCase(realCase('CASE-0002'));
    expect(detail.status).toBe('reopened');
    expect(detail.reopen_count).toBe(1);

    // Step 8: second investigation with reopen_of → inventory
    const second = await call(m.mockStartInvestigation, { case_id: 'CASE-0002', reopen_of: start.investigation_id }, ctx);
    expect(second.reopen_of).toBe(start.investigation_id);
    expect(second.hypotheses.find((h) => h.cause_category === 'packing').rationale).toMatch(/Last fix failed/);
    const secondDone = await pollToRest(second.investigation_id);
    expect(secondDone.result.cause_category).toBe('inventory');
    expect(m.applyMockCase(realCase('CASE-0002')).investigation_ids).toEqual([second.investigation_id, start.investigation_id]);

    // First run still readable for PreviousInvestigation
    const first = await call(m.mockGetInvestigation, start.investigation_id, ctx);
    expect(first.result.cause_category).toBe('packing');

    // Approve → recheck → improved → closed
    const action2 = await call(m.mockGetProposal, secondDone.result.proposal_id, ctx);
    expect(action2.proposal_id).not.toBe(action.proposal_id);
    await decide(action2, 'approve');
    const rck2 = m.applyMockCase(realCase('CASE-0002')).rechecks.find((r) => r.status === 'scheduled');
    expect((await call(m.mockRunRecheck, rck2.recheck_id, ctx)).status).toBe('improved');
    expect(caseStatus('CASE-0002')).toBe('closed');

    // Audit trail
    const auditRows = await call(m.mockListAudit, 'CASE-0002', { user: analyst, opened_at: '2026-11-15T09:00:00Z' });
    expect(auditRows[0].action).toBe('case.opened');
    expect(auditRows.map((a) => a.action)).toEqual(expect.arrayContaining([
      'investigation.started', 'proposal.created', 'proposal.edited', 'proposal.approved', 'dispatch.sent',
      'merchant_reply.recorded', 'investigation.completed', 'recheck.scheduled', 'recheck.not_improved', 'recheck.improved',
    ]));
  });
});

describe('other endings', () => {
  it('rejected question → unsure → analyst_review', async () => {
    const start = await call(m.mockStartInvestigation, { case_id: 'CASE-0002', reopen_of: null }, ctx);
    const paused = await pollToRest(start.investigation_id);
    const q = await call(m.mockGetProposal, paused.pending_proposal_id, ctx);
    await decide(q, 'reject');
    expect(caseStatus('CASE-0002')).toBe('investigating');
    await resume(start.investigation_id);
    const done = await pollToRest(start.investigation_id);
    expect(done.status).toBe('unsure');
    expect(done.result.evidence_gaps.join(' ')).toContain(`${q.proposal_id} was rejected`);
    expect(caseStatus('CASE-0002')).toBe('analyst_review');
  });

  it('no reply → unsure', async () => {
    const start = await call(m.mockStartInvestigation, { case_id: 'CASE-0002', reopen_of: null }, ctx);
    const paused = await pollToRest(start.investigation_id);
    const q = await call(m.mockGetProposal, paused.pending_proposal_id, ctx);
    await decide(q, 'approve');
    await resume(start.investigation_id);
    await call(m.mockRecordReply, q.proposal_id, { outcome: 'no_reply', text: null }, ctx);
    await resume(start.investigation_id);
    expect((await pollToRest(start.investigation_id)).status).toBe('unsure');
  });

  it('CASE-0001: completed → approve → improved → closed', async () => {
    const start = await call(m.mockStartInvestigation, { case_id: 'CASE-0001', reopen_of: null }, ctx);
    const done = await pollToRest(start.investigation_id);
    expect(done.status).toBe('completed');
    const action = await call(m.mockGetProposal, done.result.proposal_id, ctx);
    expect(action.kind).toBe('handoff');
    await decide(action, 'approve');
    const rck = m.applyMockCase(realCase('CASE-0001')).rechecks[0];
    expect((await call(m.mockRunRecheck, rck.recheck_id, ctx)).status).toBe('improved');
    expect(caseStatus('CASE-0001')).toBe('closed');
  });

  it('rejected action → analyst_review', async () => {
    const start = await call(m.mockStartInvestigation, { case_id: 'CASE-0001', reopen_of: null }, ctx);
    const done = await pollToRest(start.investigation_id);
    await decide(await call(m.mockGetProposal, done.result.proposal_id, ctx), 'reject');
    expect(caseStatus('CASE-0001')).toBe('analyst_review');
    expect(m.applyMockCase(realCase('CASE-0001')).rechecks).toHaveLength(0);
  });

  it('insufficient data → paused', async () => {
    const start = await call(m.mockStartInvestigation, { case_id: 'CASE-0001', reopen_of: null }, ctx);
    const done = await pollToRest(start.investigation_id);
    await decide(await call(m.mockGetProposal, done.result.proposal_id, ctx), 'approve');
    m.setNextRecheck('insufficient_data');
    const rck = await call(m.mockRunRecheck, m.applyMockCase(realCase('CASE-0001')).rechecks[0].recheck_id, ctx);
    expect(rck.data_sufficient).toBe(false);
    expect(rck.after.rate).toBeNull();
    expect(caseStatus('CASE-0001')).toBe('paused');
  });

  it('second not-improved → analyst_review, and no third run', async () => {
    const { inv } = await packingToResult();
    await decide(await call(m.mockGetProposal, inv.result.proposal_id, ctx), 'approve');
    await call(m.mockRunRecheck, m.applyMockCase(realCase('CASE-0002')).rechecks[0].recheck_id, ctx);
    const second = await call(m.mockStartInvestigation, { case_id: 'CASE-0002', reopen_of: inv.investigation_id }, ctx);
    const done = await pollToRest(second.investigation_id);
    await decide(await call(m.mockGetProposal, done.result.proposal_id, ctx), 'approve');
    m.setNextRecheck('not_improved');
    const rck2 = m.applyMockCase(realCase('CASE-0002')).rechecks.find((r) => r.status === 'scheduled');
    await call(m.mockRunRecheck, rck2.recheck_id, ctx);
    expect(caseStatus('CASE-0002')).toBe('analyst_review');
    const err = await fail(m.mockStartInvestigation, { case_id: 'CASE-0002', reopen_of: second.investigation_id }, ctx);
    expect(err.data.error.code).toBe('REOPEN_NOT_ALLOWED');
  });
});

describe('errors and guards', () => {
  it('failed run with a chosen code → case open with last_error; Start again works', async () => {
    m.failNextStart('RUN_TIMEOUT');
    const start = await call(m.mockStartInvestigation, { case_id: 'CASE-0001', reopen_of: null }, ctx);
    const done = await pollToRest(start.investigation_id);
    expect(done.status).toBe('failed');
    expect(done.error.code).toBe('RUN_TIMEOUT');
    const detail = m.applyMockCase(realCase('CASE-0001'));
    expect(detail.status).toBe('open');
    expect(detail.last_error).toBe('RUN_TIMEOUT');
    const again = await call(m.mockStartInvestigation, { case_id: 'CASE-0001', reopen_of: null }, ctx);
    expect(again.status).toBe('running');
    expect(m.applyMockCase(realCase('CASE-0001')).last_error).toBeNull();
  });

  it('DISPATCH_FAILED keeps the proposal pending; approving again works', async () => {
    const start = await call(m.mockStartInvestigation, { case_id: 'CASE-0001', reopen_of: null }, ctx);
    const done = await pollToRest(start.investigation_id);
    const action = await call(m.mockGetProposal, done.result.proposal_id, ctx);
    m.failNextDispatch();
    const err = await fail(decide, action, 'approve', 'same-key');
    expect(err.status).toBe(502);
    expect((await call(m.mockGetProposal, action.proposal_id, ctx)).status).toBe('pending');
    expect(caseStatus('CASE-0001')).toBe('awaiting_decision');
    expect((await decide(action, 'approve', 'same-key')).status).toBe('approved');
  });

  it('INVESTIGATION_ACTIVE carries the running investigation_id', async () => {
    const start = await call(m.mockStartInvestigation, { case_id: 'CASE-0001', reopen_of: null }, ctx);
    const err = await fail(m.mockStartInvestigation, { case_id: 'CASE-0001', reopen_of: null }, ctx);
    expect(err.status).toBe(409);
    expect(err.data.error.details.investigation_id).toBe(start.investigation_id);
  });

  it('reopen_of on a case that is not reopened → REOPEN_NOT_ALLOWED', async () => {
    const start = await call(m.mockStartInvestigation, { case_id: 'CASE-0001', reopen_of: null }, ctx);
    await pollToRest(start.investigation_id);
    const err = await fail(m.mockStartInvestigation, { case_id: 'CASE-0001', reopen_of: start.investigation_id }, ctx);
    expect(err.data.error.code).toBe('REOPEN_NOT_ALLOWED');
  });

  it('viewer: reads its store, cannot decide, cannot see STORE-B', async () => {
    const start = await call(m.mockStartInvestigation, { case_id: 'CASE-0001', reopen_of: null }, ctx);
    const done = await pollToRest(start.investigation_id);
    const asViewer = { user: viewer };
    const p = await call(m.mockGetProposal, done.result.proposal_id, asViewer);
    expect((await fail(m.mockDecideProposal, p.proposal_id, { version: 1, decision: 'approve' }, asViewer)).status).toBe(403);
    expect((await call(m.mockGetEvidence, 'EV-CLM-004410', asViewer)).store_id).toBe('STORE-A');
    expect((await fail(m.mockGetEvidence, 'EV-CLM-006131', asViewer)).status).toBe(404);
    expect((await fail(m.mockListAudit, 'CASE-0002', asViewer)).status).toBe(404);
  });

  it('every evidence ID cited by a scenario resolves', async () => {
    const { inv } = await packingToResult();
    const cited = new Set(JSON.stringify(inv).match(/EV-(CLM|CXL|EVT)-\d{6}/g));
    cited.forEach((id) => expect(EVIDENCE[id], id).toBeDefined());
  });

  it('untouched cases pass through the overlay unchanged', () => {
    const real = realCase('CASE-0001');
    expect(m.applyMockCase(real)).toBe(real);
  });
});

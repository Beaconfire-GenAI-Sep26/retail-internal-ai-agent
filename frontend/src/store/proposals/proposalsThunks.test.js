// decideProposal / editProposal against the real-API branch (axios faked):
// the request sent, and what the UI does on each refusal (ui-workflow.md v0.3).
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { configureStore } from '@reduxjs/toolkit';

vi.mock('../../api/mockAuth', () => ({ USE_MOCKS: false }));
vi.mock('../../api/axios', () => ({
  default: { get: vi.fn(), post: vi.fn() },
  injectStore: vi.fn(),
  invalidateSession: vi.fn(),
  refreshSession: vi.fn(),
}));
vi.mock('../cases/casesThunks', () => ({
  fetchCase: (caseId) => ({ type: 'test/fetchCase', payload: caseId }),
}));

const { default: api } = await import('../../api/axios');
const { default: proposals } = await import('./proposalsSlice');
const { decideProposal, editProposal } = await import('./proposalsThunks');

const v1 = { proposal_id: 'PROP-0001', case_id: 'CASE-0001', version: 1, status: 'pending', content: { title: 'T', instructions: 'I' } };
const httpError = (status, code) => ({ response: { status, data: { error: { code, message: `${code} from server` } } } });

// Records every action so the test can see which follow-up calls were made
let seen;
const makeStore = () => {
  seen = [];
  const store = configureStore({
    reducer: { proposals, auth: () => ({ user: { user_id: 'USR-001', role: 'loe_analyst' } }) },
    middleware: (gdm) => gdm().concat(() => (next) => (action) => { seen.push(action.type); return next(action); }),
  });
  return store;
};

beforeEach(() => {
  api.get.mockReset();
  api.post.mockReset();
});

describe('decideProposal', () => {
  it('sends version, decision, a trimmed note and the Idempotency-Key, then reloads the case', async () => {
    const store = makeStore();
    api.post.mockResolvedValue({ data: { ...v1, status: 'approved' } });

    await store.dispatch(decideProposal({ id: 'PROP-0001', version: 1, decision: 'approve', note: '  ok  ', idempotencyKey: 'k1' }));

    expect(api.post).toHaveBeenCalledWith(
      '/domain/proposals/PROP-0001/decision',
      { version: 1, decision: 'approve', note: 'ok' },
      { headers: { 'Idempotency-Key': 'k1' } },
    );
    expect(store.getState().proposals.byId['PROP-0001'].status).toBe('approved');
    expect(seen).toContain('test/fetchCase');
  });

  it('an empty note is sent as null', async () => {
    const store = makeStore();
    api.post.mockResolvedValue({ data: v1 });
    await store.dispatch(decideProposal({ id: 'PROP-0001', version: 1, decision: 'reject', note: '   ', idempotencyKey: 'k1' }));
    expect(api.post.mock.calls[0][1].note).toBeNull();
  });

  it('STALE_VERSION → reloads the proposal and says someone edited it', async () => {
    const store = makeStore();
    api.post.mockRejectedValue(httpError(409, 'STALE_VERSION'));
    api.get.mockResolvedValue({ data: { ...v1, version: 2 } });

    const result = await store.dispatch(decideProposal({ id: 'PROP-0001', version: 1, decision: 'approve', idempotencyKey: 'k1' }));
    await vi.waitFor(() => expect(store.getState().proposals.byId['PROP-0001']?.version).toBe(2));

    expect(result.payload).toMatchObject({ code: 'STALE_VERSION', noResponse: false });
    expect(result.payload.message).toMatch(/Someone edited it/);
    expect(api.get).toHaveBeenCalledWith('/domain/proposals/PROP-0001');
  });

  it('ALREADY_DECIDED → reloads the proposal and the case', async () => {
    const store = makeStore();
    store.dispatch({ type: 'proposals/fetchOne/fulfilled', payload: v1, meta: { arg: 'PROP-0001' } });
    api.post.mockRejectedValue(httpError(409, 'ALREADY_DECIDED'));
    api.get.mockResolvedValue({ data: { ...v1, status: 'rejected' } });

    const result = await store.dispatch(decideProposal({ id: 'PROP-0001', version: 1, decision: 'approve', idempotencyKey: 'k1' }));

    expect(result.payload.message).toMatch(/Already decided/);
    expect(api.get).toHaveBeenCalled();
    expect(seen).toContain('test/fetchCase');
  });

  it('DISPATCH_FAILED → still pending, approve again (a response came back)', async () => {
    const store = makeStore();
    api.post.mockRejectedValue(httpError(502, 'DISPATCH_FAILED'));
    const result = await store.dispatch(decideProposal({ id: 'PROP-0001', version: 1, decision: 'approve', idempotencyKey: 'k1' }));
    expect(result.payload).toMatchObject({ code: 'DISPATCH_FAILED', noResponse: false });
    expect(result.payload.message).toMatch(/approve again/);
    expect(store.getState().proposals.writeById['PROP-0001'].status).toBe('failed');
  });

  it('no response → noResponse, so the same key may be retried', async () => {
    const store = makeStore();
    api.post.mockRejectedValue(new Error('Network Error'));
    const result = await store.dispatch(decideProposal({ id: 'PROP-0001', version: 1, decision: 'approve', idempotencyKey: 'k1' }));
    expect(result.payload.noResponse).toBe(true);
  });
});

describe('editProposal', () => {
  it('posts the new content and stores the next version', async () => {
    const store = makeStore();
    api.post.mockResolvedValue({ data: { ...v1, version: 2, content: { title: 'New', instructions: 'I' } } });
    await store.dispatch(editProposal({ id: 'PROP-0001', content: { title: 'New', instructions: 'I' } }));
    expect(api.post).toHaveBeenCalledWith('/domain/proposals/PROP-0001/versions', { content: { title: 'New', instructions: 'I' } });
    expect(store.getState().proposals.byId['PROP-0001'].version).toBe(2);
    expect(store.getState().proposals.writeById['PROP-0001']).toBeUndefined();
  });
});

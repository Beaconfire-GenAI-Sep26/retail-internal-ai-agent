// runRecheck and startInvestigation(reopen_of) against the real-API branch (axios faked)
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
const { default: rechecks } = await import('./rechecksSlice');
const { runRecheck } = await import('./rechecksThunks');
const { startInvestigation } = await import('../investigations/investigationsThunks');

let seen;
const makeStore = () => {
  seen = [];
  return configureStore({
    reducer: { rechecks, auth: () => ({ user: { user_id: 'USR-001', role: 'loe_analyst' } }) },
    middleware: (gdm) => gdm().concat(() => (next) => (action) => { seen.push(action.type); return next(action); }),
  });
};
const httpError = (status, code) => ({ response: { status, data: { error: { code, message: code } } } });

beforeEach(() => {
  api.get.mockReset();
  api.post.mockReset();
});

describe('runRecheck', () => {
  it('posts an empty body with the Idempotency-Key, then reloads the case', async () => {
    const store = makeStore();
    api.post.mockResolvedValue({ data: { recheck_id: 'RCK-0001', status: 'improved' } });
    await store.dispatch(runRecheck({ id: 'RCK-0001', caseId: 'CASE-0001', idempotencyKey: 'k1' }));
    expect(api.post).toHaveBeenCalledWith('/domain/rechecks/RCK-0001/run', null, { headers: { 'Idempotency-Key': 'k1' } });
    expect(seen).toContain('test/fetchCase');
    expect(store.getState().rechecks.runById['RCK-0001']).toBeUndefined();
  });

  it('RECHECK_ALREADY_RUN → reloads the case to show the result', async () => {
    const store = makeStore();
    api.post.mockRejectedValue(httpError(409, 'RECHECK_ALREADY_RUN'));
    const result = await store.dispatch(runRecheck({ id: 'RCK-0001', caseId: 'CASE-0001', idempotencyKey: 'k1' }));
    expect(result.payload.code).toBe('RECHECK_ALREADY_RUN');
    expect(seen).toContain('test/fetchCase');
    expect(store.getState().rechecks.runById['RCK-0001'].status).toBe('failed');
  });
});

describe('startInvestigation', () => {
  it('a first run sends reopen_of null', async () => {
    api.post.mockResolvedValue({ data: { investigation_id: 'INV-1', status: 'running' } });
    await makeStore().dispatch(startInvestigation({ caseId: 'CASE-0002' }));
    expect(api.post).toHaveBeenCalledWith('/agent/investigations', { case_id: 'CASE-0002', reopen_of: null });
  });

  it('"Start new investigation" sends the run whose fix did not work', async () => {
    api.post.mockResolvedValue({ data: { investigation_id: 'INV-2', status: 'running' } });
    await makeStore().dispatch(startInvestigation({ caseId: 'CASE-0002', reopenOf: 'INV-1' }));
    expect(api.post).toHaveBeenCalledWith('/agent/investigations', { case_id: 'CASE-0002', reopen_of: 'INV-1' });
  });
});

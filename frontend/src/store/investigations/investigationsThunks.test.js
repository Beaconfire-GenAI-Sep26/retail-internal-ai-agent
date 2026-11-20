// startInvestigation against the real-API branch (axios faked): reopen_of,
// the token refresh before Start, and the two 409s the UI recovers from.
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

const { default: api, refreshSession } = await import('../../api/axios');
const { default: investigations } = await import('./investigationsSlice');
const { startInvestigation } = await import('./investigationsThunks');

const inMinutes = (n) => new Date(Date.now() + n * 60 * 1000).toISOString();
let seen;
const makeStore = (expiresAt = inMinutes(50)) => {
  seen = [];
  return configureStore({
    reducer: {
      investigations,
      auth: () => ({ user: { user_id: 'USR-001', role: 'loe_analyst' }, token: 't', expiresAt }),
    },
    middleware: (gdm) => gdm().concat(() => (next) => (action) => { seen.push(action.type); return next(action); }),
  });
};
const httpError = (status, code, details = null) => ({ response: { status, data: { error: { code, message: code, details } } } });

beforeEach(() => {
  api.get.mockReset();
  api.post.mockReset();
  refreshSession.mockReset();
});

describe('startInvestigation — request', () => {
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

describe('startInvestigation — fresh token', () => {
  it('more than 25 min left → no refresh', async () => {
    api.post.mockResolvedValue({ data: { investigation_id: 'INV-1' } });
    await makeStore(inMinutes(40)).dispatch(startInvestigation({ caseId: 'CASE-0001' }));
    expect(refreshSession).not.toHaveBeenCalled();
  });

  it('less than 25 min left → refresh, then Start', async () => {
    const order = [];
    refreshSession.mockImplementation(async () => { order.push('refresh'); });
    api.post.mockImplementation(async () => { order.push('start'); return { data: { investigation_id: 'INV-1' } }; });
    await makeStore(inMinutes(10)).dispatch(startInvestigation({ caseId: 'CASE-0001' }));
    expect(order).toEqual(['refresh', 'start']);
  });

  it('refresh fails → signed out, no Start sent', async () => {
    refreshSession.mockRejectedValue(new Error('401'));
    const result = await makeStore(inMinutes(5)).dispatch(startInvestigation({ caseId: 'CASE-0001' }));
    expect(api.post).not.toHaveBeenCalled();
    expect(seen).toContain('auth/credentialsCleared');
    expect(result.payload).toMatch(/sign in again/);
  });
});

describe('startInvestigation — refusals', () => {
  it('INVESTIGATION_ACTIVE → shows the run that is already active, not an error', async () => {
    const store = makeStore();
    api.post.mockRejectedValue(httpError(409, 'INVESTIGATION_ACTIVE', { investigation_id: 'INV-9' }));
    api.get.mockResolvedValue({ data: { investigation_id: 'INV-9', case_id: 'CASE-0001', status: 'running' } });

    const result = await store.dispatch(startInvestigation({ caseId: 'CASE-0001' }));

    expect(startInvestigation.fulfilled.match(result)).toBe(true);
    expect(api.get).toHaveBeenCalledWith('/agent/investigations/INV-9');
    expect(store.getState().investigations.current.investigation_id).toBe('INV-9');
    expect(store.getState().investigations.startError).toBeNull();
  });

  it('REOPEN_NOT_ALLOWED → reloads the case and explains', async () => {
    api.post.mockRejectedValue(httpError(409, 'REOPEN_NOT_ALLOWED'));
    const result = await makeStore().dispatch(startInvestigation({ caseId: 'CASE-0001', reopenOf: 'INV-1' }));
    expect(seen).toContain('test/fetchCase');
    expect(result.payload).toMatch(/out of date/);
  });
});

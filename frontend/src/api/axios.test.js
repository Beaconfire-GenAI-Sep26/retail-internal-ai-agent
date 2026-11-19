import { beforeEach, afterEach, describe, expect, it, vi } from 'vitest';
import axios, { AxiosError } from 'axios';

// Isolate the transport from Redux's thunk/slice import cycle.
vi.mock('../store/auth/authSlice', () => ({
  sessionRefreshed: (payload) => ({ type: 'refreshed', payload }),
  credentialsCleared: () => ({ type: 'cleared' }),
}));
import api, { injectStore, refreshSession, invalidateSession } from './axios';

const user = { user_id: 'USR-001', role: 'loe_analyst', store_ids: ['STORE-A'] };
const fresh = { access_token: 'new-token', user };
const deferred = () => {
  let resolve, reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
};
const success = (config) => ({ status: 200, data: { ok: true }, config, headers: {} });
const expired = (config) => new AxiosError('Expired', 'ERR_BAD_REQUEST', config, null,
  { status: 401, data: {}, config, headers: {} });

describe('session refresh transport', () => {
  let state, dispatch;
  beforeEach(() => {
    invalidateSession();
    state = { auth: { token: 'old-token', user } };
    dispatch = vi.fn((action) => {
      if (action.type === 'refreshed') Object.assign(state.auth, action.payload);
      if (action.type === 'cleared') state.auth = { token: null, user: null };
    });
    injectStore({ getState: () => state, dispatch });
  });
  afterEach(() => vi.restoreAllMocks());

  it('shares one refresh between simultaneous 401s and retries each request', async () => {
    const gate = deferred();
    const refresh = vi.spyOn(axios, 'post').mockReturnValue(gate.promise);
    api.defaults.adapter = vi.fn(async (config) => {
      if (config.headers.Authorization === 'Bearer old-token') throw expired(config);
      return success(config);
    });
    const first = api.get('/domain/cases');
    const second = api.get('/domain/stores/STORE-A');
    await vi.waitFor(() => expect(refresh).toHaveBeenCalledTimes(1));
    gate.resolve({ data: fresh });
    expect((await Promise.all([first, second])).every((r) => r.status === 200)).toBe(true);
    expect(state.auth.user).toEqual(user);
    expect(state.auth.token).toBe('new-token');
    expect(api.defaults.adapter).toHaveBeenCalledTimes(4);
  });

  it('shares bootstrap refresh calls, including StrictMode', async () => {
    const gate = deferred();
    const refresh = vi.spyOn(axios, 'post').mockReturnValue(gate.promise);
    const first = refreshSession();
    const second = refreshSession();
    expect(first).toBe(second);
    gate.resolve({ data: fresh });
    await first;
    expect(refresh).toHaveBeenCalledTimes(1);
  });

  it('uses an already-refreshed token for a late 401', async () => {
    const refresh = vi.spyOn(axios, 'post');
    const delayed = deferred();
    api.defaults.adapter = vi.fn(async (config) => {
      if (!config._retry) {
        await delayed.promise;
        throw expired(config);
      }
      return success(config);
    });
    const request = api.get('/domain/cases');
    await vi.waitFor(() => expect(api.defaults.adapter).toHaveBeenCalledTimes(1));
    state.auth.token = 'new-token';
    delayed.resolve();
    expect((await request).status).toBe(200);
    expect(refresh).not.toHaveBeenCalled();
  });

  it('clears expired sessions when refresh fails', async () => {
    vi.spyOn(axios, 'post').mockRejectedValue(new Error('refresh revoked'));
    api.defaults.adapter = vi.fn(async (config) => { throw expired(config); });
    await expect(api.get('/domain/cases')).rejects.toThrow('refresh revoked');
    expect(state.auth.token).toBeNull();
    expect(api.defaults.adapter).toHaveBeenCalledTimes(1);
  });

  it('does not refresh bad login, logout, or a 403', async () => {
    const refresh = vi.spyOn(axios, 'post');
    api.defaults.adapter = vi.fn(async (config) => {
      const error = expired(config);
      if (config.url === '/domain/denied') error.response.status = 403;
      throw error;
    });
    for (const path of ['/auth/login', '/auth/logout', '/domain/denied']) {
      await expect(api.post(path)).rejects.toBeInstanceOf(AxiosError);
    }
    expect(refresh).not.toHaveBeenCalled();
  });

  it('retries only once if the replacement token is also rejected', async () => {
    const refresh = vi.spyOn(axios, 'post').mockResolvedValue({ data: fresh });
    api.defaults.adapter = vi.fn(async (config) => { throw expired(config); });
    await expect(api.get('/domain/cases')).rejects.toBeInstanceOf(AxiosError);
    expect(refresh).toHaveBeenCalledTimes(1);
    expect(api.defaults.adapter).toHaveBeenCalledTimes(2);
    expect(state.auth.token).toBeNull();
  });

  it('does not restore credentials after logout invalidates an in-flight refresh', async () => {
    const gate = deferred();
    vi.spyOn(axios, 'post').mockReturnValue(gate.promise);
    const pending = refreshSession();
    invalidateSession();
    state.auth = { token: null, user: null };
    gate.resolve({ data: fresh });
    await expect(pending).rejects.toThrow('Session changed');
    expect(state.auth.token).toBeNull();
    expect(dispatch).not.toHaveBeenCalled();
  });

  it('preserves explicit credentials instead of overwriting with a stale token', async () => {
    api.defaults.adapter = vi.fn(async (config) => success(config));
    const response = await api.get('/auth/me', { headers: { Authorization: 'Bearer explicit-token' } });
    expect(response.config.headers.Authorization).toBe('Bearer explicit-token');
  });
});

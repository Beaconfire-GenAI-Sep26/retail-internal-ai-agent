import { expect, it } from 'vitest';
import reducer, { sessionRefreshed } from './authSlice';
import { bootstrap, login, logout } from './authThunks';

const session = { token: 'restored-token', user: { user_id: 'USR-001', role: 'loe_analyst' } };

it('keeps expiry metadata after refresh and clears it on logout', () => {
  const expiresAt = '2026-11-19T23:00:00Z';
  let state = reducer(undefined, sessionRefreshed({ ...session, expiresAt }));
  expect(state.expiresAt).toBe(expiresAt);
  state = reducer(state, logout.pending('logout'));
  expect(state.expiresAt).toBeNull();
});

it('ignores a bootstrap fulfillment queued before logout', () => {
  let state = reducer(undefined, bootstrap.pending('restore'));
  state = reducer(state, logout.pending('logout'));
  state = reducer(state, bootstrap.fulfilled(session, 'restore'));
  expect(state.token).toBeNull();
  expect(state.user).toBeNull();
});

it('ignores an older bootstrap after a new login has started', () => {
  let state = reducer(undefined, bootstrap.pending('restore'));
  state = reducer(state, login.pending('login'));
  state = reducer(state, bootstrap.fulfilled(session, 'restore'));
  expect(state.token).toBeNull();
  expect(state.status).toBe('loading');
});

it('uses the latest StrictMode bootstrap and marks restoration complete', () => {
  let state = reducer(undefined, bootstrap.pending('first'));
  state = reducer(state, bootstrap.pending('second'));
  state = reducer(state, bootstrap.fulfilled(session, 'first'));
  expect(state.token).toBeNull();
  state = reducer(state, bootstrap.fulfilled(session, 'second'));
  expect(state.token).toBe(session.token);
  expect(state.bootstrapped).toBe(true);
});

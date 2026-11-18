// [05a] Auth thunks — async calls to /auth/* (Auth Service, A-02)
// Login uses username; no register (accounts are seeded); mock branch when USE_MOCKS


// ═══════════════════════════════════════════════════════════════════
// 1. Imports
// ═══════════════════════════════════════════════════════════════════
import { createAsyncThunk } from '@reduxjs/toolkit';
import api from '../../api/axios';
import { getErrorMessage } from '../../api/errors';
import { USE_MOCKS, mockLogin, mockBootstrap, mockLogout } from '../../api/mockAuth';

// createAsyncThunk wraps an async function and auto-dispatches three actions —
// pending / fulfilled / rejected — that authSlice responds to in extraReducers.
// Every thunk resolves to the same shape: { token, user }


// ═══════════════════════════════════════════════════════════════════
// 2. login — POST /auth/login → GET /auth/me
// ═══════════════════════════════════════════════════════════════════
// Log in, then fetch the profile so the store gets BOTH the access token and who
// the analyst is (role + store_ids). The fresh token is attached to /auth/me by
// hand because it is not in the store yet at this moment.
export const login = createAsyncThunk(
  'auth/login',
  async ({ username, password }, { rejectWithValue }) => {
    if (USE_MOCKS) {
      try {
        return await mockLogin({ username, password });
      } catch (err) {
        return rejectWithValue(err.message);
      }
    }

    try {
      const { data } = await api.post('/auth/login', { username, password });
      const me = await api.get('/auth/me', {
        headers: { Authorization: `Bearer ${data.access_token}` },
      });
      return { token: data.access_token, user: me.data };
    } catch (err) {
      // rejectWithValue puts this string on action.payload so the slice can show it
      return rejectWithValue(getErrorMessage(err, 'Login failed'));
    }
  },
);


// ═══════════════════════════════════════════════════════════════════
// 3. bootstrap — POST /auth/refresh → GET /auth/me (on page load)
// ═══════════════════════════════════════════════════════════════════
// The access token lives only in memory, so a hard refresh would log the analyst
// out; instead we exchange the HttpOnly refresh cookie for a new access token and
// re-fetch the profile. No valid cookie → 401 → we simply stay logged out.
export const bootstrap = createAsyncThunk(
  'auth/bootstrap',
  async (_, { rejectWithValue }) => {
    try {
      if (USE_MOCKS) return await mockBootstrap();

      const { data } = await api.post('/auth/refresh');
      const me = await api.get('/auth/me', {
        headers: { Authorization: `Bearer ${data.access_token}` },
      });
      return { token: data.access_token, user: me.data };
    } catch {
      // Silent: "not logged in" is a normal outcome on first visit
      return rejectWithValue(null);
    }
  },
);


// ═══════════════════════════════════════════════════════════════════
// 4. logout — POST /auth/logout
// ═══════════════════════════════════════════════════════════════════
// Revoke the refresh token on the backend and clear the cookie. The local session
// is cleared regardless of whether the network call succeeds (see authSlice).
export const logout = createAsyncThunk('auth/logout', async () => {
  try {
    if (USE_MOCKS) {
      await mockLogout();
      return;
    }
    await api.post('/auth/logout');
  } catch {
    // ignore — the client session is cleared either way
  }
});

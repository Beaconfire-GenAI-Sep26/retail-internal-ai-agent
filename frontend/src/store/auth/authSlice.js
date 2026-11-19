// [05b] Auth slice — who is logged in, the access token, the login error


// ═══════════════════════════════════════════════════════════════════
// 1. Imports
// ═══════════════════════════════════════════════════════════════════
import { createSlice } from '@reduxjs/toolkit';
import { login, bootstrap, logout } from './authThunks';


// ═══════════════════════════════════════════════════════════════════
// 2. Initial state
// ═══════════════════════════════════════════════════════════════════
const initialState = {
  user: null, // { user_id, display_name, role, store_ids } — shared User DTO
  token: null, // access token, kept in memory only (never localStorage)
  status: 'idle', // 'idle' | 'loading' | 'succeeded' | 'failed' — last login attempt
  loginError: null, // message shown on the login form
  bootstrapped: false, // has the on-load session restore finished yet?
  bootstrapRequestId: null,
};

// Logged-out state that keeps bootstrapped = true (we already know there is no
// session) — shared by logout and credentialsCleared
const loggedOut = { ...initialState, bootstrapped: true };


// ═══════════════════════════════════════════════════════════════════
// 3. Slice — sync reducers + thunk lifecycle
// ═══════════════════════════════════════════════════════════════════
const authSlice = createSlice({
  name: 'auth',
  initialState,

  // ── 3a. reducers — dispatched by the axios interceptor ──────────
  reducers: {
    // Store a freshly refreshed access token (after a silent /auth/refresh)
    sessionRefreshed(state, action) {
      state.token = action.payload.token;
      state.user = action.payload.user;
    },
    // Wipe the session when a silent refresh fails
    credentialsCleared() {
      return loggedOut;
    },
  },

  // ── 3b. extraReducers — pending / fulfilled / rejected per thunk ──
  extraReducers: (builder) => {
    builder
      // login — clears its own error on each attempt so a retry starts clean
      .addCase(login.pending, (state) => {
        state.status = 'loading';
        state.loginError = null;
        state.bootstrapRequestId = null;
      })
      .addCase(login.fulfilled, (state, action) => {
        state.status = 'succeeded';
        state.token = action.payload.token;
        state.user = action.payload.user;
        state.bootstrapped = true;
      })
      .addCase(login.rejected, (state, action) => {
        state.status = 'failed';
        state.loginError = action.payload ?? 'Login failed';
      })
      // bootstrap — session restore is silent, so failure surfaces no error
      .addCase(bootstrap.pending, (state, action) => {
        state.bootstrapRequestId = action.meta.requestId;
      })
      .addCase(bootstrap.fulfilled, (state, action) => {
        if (state.bootstrapRequestId !== action.meta.requestId) return;
        state.token = action.payload.token;
        state.user = action.payload.user;
        state.bootstrapped = true;
        state.bootstrapRequestId = null;
      })
      .addCase(bootstrap.rejected, (state, action) => {
        if (state.bootstrapRequestId !== action.meta.requestId) return;
        state.bootstrapped = true;
        state.bootstrapRequestId = null;
      })
      // logout — back to a clean, logged-out state
      .addCase(logout.pending, () => loggedOut)
      .addCase(logout.fulfilled, () => loggedOut);
  },
});


// ═══════════════════════════════════════════════════════════════════
// 4. Exports — actions for axios.js, reducer for store.js
// ═══════════════════════════════════════════════════════════════════
export const { sessionRefreshed, credentialsCleared } = authSlice.actions;

export default authSlice.reducer;

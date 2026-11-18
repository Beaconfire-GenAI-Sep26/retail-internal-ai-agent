// [03a] Axios instance — the ONLY place that talks HTTP to the backend
// All requests go through the API Gateway: /auth/*, /agent/*, /domain/*
// Thunks import `api` from here; components never call axios directly.


// ═══════════════════════════════════════════════════════════════════
// 1. Imports
// ═══════════════════════════════════════════════════════════════════
import axios from 'axios';
import { setToken, credentialsCleared } from '../store/auth/authSlice';
import { selectToken } from '../store/auth/authSelectors';


// ═══════════════════════════════════════════════════════════════════
// 2. Store injection — breaks the store ↔ axios circular import
// ═══════════════════════════════════════════════════════════════════
// The Redux store is handed to us by store/store.js once it has been created, so
// this module never imports the store directly (that would be a circular import:
// store -> slices -> thunks -> axios -> store).
let store;
export const injectStore = (_store) => {
  store = _store;
};


// ═══════════════════════════════════════════════════════════════════
// 3. Axios instance — base URL from env
// ═══════════════════════════════════════════════════════════════════
// "API base URL is configurable" (D-01 acceptance):
// - empty (Docker build) → same-origin paths (/auth/login, /domain/cases ...)
//   that the API Gateway routes to each service — no CORS
// - local dev → set VITE_API_URL in .env to a running gateway
// withCredentials: send the HttpOnly refresh_token cookie on /auth/refresh, /auth/logout
const api = axios.create({
  baseURL: import.meta.env.VITE_API_URL ?? '',
  withCredentials: true,
});


// ═══════════════════════════════════════════════════════════════════
// 4. Request interceptor — attach "Authorization: Bearer <token>"
// ═══════════════════════════════════════════════════════════════════
// Components and thunks never set the header themselves. The token is read
// through the same selector components use, so the store shape lives in one place.
api.interceptors.request.use((config) => {
  const token = store ? selectToken(store.getState()) : null;
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});


// ═══════════════════════════════════════════════════════════════════
// 5. Silent refresh — one shared /auth/refresh call
// ═══════════════════════════════════════════════════════════════════
// ⚠ Depends on A-02 providing POST /auth/refresh — confirm with Quang.
// When the access token expires the backend replies 401. Instead of forcing a
// re-login, we call /auth/refresh (authenticated by the HttpOnly cookie), store
// the new token, and replay the failed request — invisible to the analyst.
// If several requests 401 at once, only ONE refresh runs; the rest await it.
let refreshPromise = null;

const refreshAccessToken = async () => {
  // Plain axios (not `api`) so this request skips the interceptors and can
  // never recurse into itself.
  const { data } = await axios.post(`${api.defaults.baseURL}/auth/refresh`, null, {
    withCredentials: true,
  });
  store.dispatch(setToken(data.access_token));
  return data.access_token;
};


// ═══════════════════════════════════════════════════════════════════
// 6. Response interceptor — on 401: refresh once, then retry
// ═══════════════════════════════════════════════════════════════════
api.interceptors.response.use(
  (response) => response,
  async (error) => {
    const original = error.config;

    // Don't refresh on these: /auth/refresh would recurse, and a 401 from login is
    // the expected "bad credentials" signal the form must show.
    const noRefresh = ['/auth/login', '/auth/refresh'];
    const skipRefresh = noRefresh.some((url) => original?.url?.includes(url));

    if (error.response?.status === 401 && !original._retry && !skipRefresh) {
      original._retry = true;
      try {
        refreshPromise = refreshPromise ?? refreshAccessToken();
        const newToken = await refreshPromise;
        refreshPromise = null;

        original.headers.Authorization = `Bearer ${newToken}`;
        return api(original);
      } catch (refreshError) {
        // Refresh failed (cookie missing / expired / revoked) — the session is
        // over. Clear it in the store and send the analyst back to login.
        refreshPromise = null;
        store.dispatch(credentialsCleared());
        window.location.href = '/login';
        return Promise.reject(refreshError);
      }
    }

    // Every other error (403 / 404 / 422 / 5xx / network) → the calling thunk's
    // catch, which turns it into a message with getErrorMessage (api/errors.js)
    return Promise.reject(error);
  },
);


// ═══════════════════════════════════════════════════════════════════
// 7. Export
// ═══════════════════════════════════════════════════════════════════
export default api;

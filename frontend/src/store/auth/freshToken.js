// [05d] freshToken — make sure the token outlives an agent run before Start
// ui-workflow.md v0.3 "Fresh token before Start":
//   - The agent uses the Start token for the whole run: up to 20 min
//     (AGENT_RUN_TIMEOUT_SECONDS), and refuses one that expires sooner (401).
//   - Tokens last 60 min (JWT_TTL_MINUTES), so without this, Start fails in the
//     last 20 min of a session.
//   1. Read the expiry: auth.expiresAt, else `exp` from the JWT (decode only).
//   2. Less than 25 min left (20 + 5 for clock drift) → POST /auth/refresh first.
//   3. Refresh failed → sign out; AuthGuard sends the analyst to /login and back
//      to this case after.
// A 401 on Start itself is still retried once by the axios interceptor (api/axios.js).
//
// Resume runs the same check: each resumed segment runs on the resume token, and
// the agent refuses one that expires within AGENT_RUN_TIMEOUT_SECONDS (resumeInvestigation).


// ═══════════════════════════════════════════════════════════════════
// 1. Imports
// ═══════════════════════════════════════════════════════════════════
import { refreshSession } from '../../api/axios';
import { USE_MOCKS } from '../../api/mockAuth';
import { credentialsCleared } from './authSlice';

export const MIN_MINUTES_LEFT = 25;


// ═══════════════════════════════════════════════════════════════════
// 2. Pure helpers (freshToken.test.js)
// ═══════════════════════════════════════════════════════════════════
// When the token expires, in ms since epoch, or null if unknown.
// RefreshResponse may carry no expires_at, so fall back to the JWT's `exp`.
export const tokenExpiryMs = (token, expiresAt) => {
  if (expiresAt) {
    const ms = Date.parse(expiresAt);
    if (!Number.isNaN(ms)) return ms;
  }
  try {
    const payload = token.split('.')[1].replace(/-/g, '+').replace(/_/g, '/');
    const { exp } = JSON.parse(atob(payload));
    return typeof exp === 'number' ? exp * 1000 : null;
  } catch {
    return null; // not a JWT (e.g. a mock token)
  }
};

// Unknown expiry counts as "refresh": a needless refresh is cheap, a failed run isn't.
export const needsRefresh = (expiryMs, nowMs, minMinutes = MIN_MINUTES_LEFT) =>
  expiryMs == null || expiryMs - nowMs < minMinutes * 60 * 1000;


// ═══════════════════════════════════════════════════════════════════
// 3. ensureFreshToken — call at the top of a thunk, before the request
// ═══════════════════════════════════════════════════════════════════
// Resolves when the token is fresh enough; rejects after signing out when the
// refresh fails. Mock mode has no Auth Service, so it does nothing there.
export const ensureFreshToken = async ({ getState, dispatch }) => {
  if (USE_MOCKS) return;
  const { token, expiresAt } = getState().auth;
  if (!needsRefresh(tokenExpiryMs(token, expiresAt), Date.now())) return;

  try {
    await refreshSession(); // stores the new token (sessionRefreshed)
  } catch (err) {
    dispatch(credentialsCleared());
    throw err;
  }
};

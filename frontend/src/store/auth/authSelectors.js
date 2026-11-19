// [05c] Auth selectors — how components and guards read state.auth


// ═══════════════════════════════════════════════════════════════════
// 1. Session selectors
// ═══════════════════════════════════════════════════════════════════
// Components read auth state through these instead of reaching into the store
// shape themselves. Each just reads a field (or a primitive derived from one),
// so there is nothing to memoize.
export const selectUser = (state) => state.auth.user;
export const selectToken = (state) => state.auth.token;
export const selectExpiresAt = (state) => state.auth.expiresAt;
export const selectIsAuthenticated = (state) => Boolean(state.auth.token);
export const selectAuthStatus = (state) => state.auth.status;
export const selectLoginError = (state) => state.auth.loginError;
export const selectBootstrapped = (state) => state.auth.bootstrapped;


// ═══════════════════════════════════════════════════════════════════
// 2. Role + store-grant selectors
// ═══════════════════════════════════════════════════════════════════
// Roles (contract `role` enum): 'loe_analyst' (LOE Analyst — investigate, decide drafts)
//                               | 'viewer' (read only)
// UI only — they decide what to SHOW. The backend re-checks role and store grant
// on every request and answers 403.
export const selectRole = (state) => state.auth.user?.role ?? null;
export const selectIsAnalyst = (state) => state.auth.user?.role === 'loe_analyst';

// Store IDs follow the C-01 seed (STORE-A ... STORE-J).
// Returns the array already in state (stable reference) — safe for useSelector.
export const selectStoreIds = (state) => state.auth.user?.store_ids;

// Usage: useSelector((state) => selectCanAccessStore(state, caseItem.store_id))
export const selectCanAccessStore = (state, storeId) =>
  Boolean(state.auth.user?.store_ids?.includes(storeId));

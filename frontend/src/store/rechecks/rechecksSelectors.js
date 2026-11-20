// [14c] Recheck selectors


// ═══════════════════════════════════════════════════════════════════
// 1. The run request for one recheck
// ═══════════════════════════════════════════════════════════════════
// → { status: 'loading' | 'failed', error } or null = nothing in flight
export const selectRecheckRun = (state, recheckId) => state.rechecks.runById[recheckId] ?? null;

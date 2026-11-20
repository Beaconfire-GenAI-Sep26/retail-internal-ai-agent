// [09c] Evidence selectors — how components read state.evidence


// ═══════════════════════════════════════════════════════════════════
// 1. The drawer
// ═══════════════════════════════════════════════════════════════════
// The evidence ID the drawer shows, or null when it is closed
export const selectOpenEvidenceId = (state) => state.evidence.openId;


// ═══════════════════════════════════════════════════════════════════
// 2. One record, by ID
// ═══════════════════════════════════════════════════════════════════
// Usage: useSelector((state) => selectEvidence(state, id))
export const selectEvidence = (state, evidenceId) => state.evidence.byId[evidenceId] ?? null;

// undefined (never asked) | 'loading' | 'succeeded' | 'failed'
export const selectEvidenceStatus = (state, evidenceId) => state.evidence.statusById[evidenceId];

export const selectEvidenceError = (state, evidenceId) => state.evidence.errorById[evidenceId] ?? null;

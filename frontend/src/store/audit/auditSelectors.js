// [15c] Audit selectors


// ═══════════════════════════════════════════════════════════════════
// 1. Helpers
// ═══════════════════════════════════════════════════════════════════
// Newest first. Same time → the later audit_id first (IDs count up).
export const newestFirst = (entries) =>
  [...entries].sort((a, b) => b.at.localeCompare(a.at) || b.audit_id.localeCompare(a.audit_id));


// ═══════════════════════════════════════════════════════════════════
// 2. Selectors
// ═══════════════════════════════════════════════════════════════════
// This case's entries as the server sent them; EMPTY for another case or before
// loading. Unsorted on purpose: sorting here would return a new array on every
// call and re-render on every store change. AuditLog sorts with newestFirst.
const EMPTY = [];
export const selectAuditEntries = (state, caseId) =>
  state.audit.caseId === caseId ? state.audit.entries : EMPTY;
export const selectAuditStatus = (state) => state.audit.status;
export const selectAuditError = (state) => state.audit.error;

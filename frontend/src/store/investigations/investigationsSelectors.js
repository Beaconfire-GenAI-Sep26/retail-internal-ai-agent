// [08c] Investigation selectors — how the case page reads state.investigations


// ═══════════════════════════════════════════════════════════════════
// 1. The investigation on screen
// ═══════════════════════════════════════════════════════════════════
// Returns it only when it belongs to the case being asked for, so a case page
// never shows the previous case's investigation for a moment.
// null means "not loaded yet" or "never investigated" — check the load status.
// Usage: useSelector((state) => selectInvestigation(state, caseId))
export const selectInvestigation = (state, caseId) =>
  state.investigations.caseId === caseId ? state.investigations.current : null;


// ═══════════════════════════════════════════════════════════════════
// 2. Request status + errors
// ═══════════════════════════════════════════════════════════════════
export const selectInvestigationLoadStatus = (state) => state.investigations.loadStatus;
export const selectInvestigationLoadError = (state) => state.investigations.loadError;
export const selectStartStatus = (state) => state.investigations.startStatus;
export const selectStartError = (state) => state.investigations.startError;
export const selectPollError = (state) => state.investigations.pollError;
// resumeInvestigation (D-05): 'idle' | 'loading' | 'failed', and { message, code, noResponse }
export const selectResumeStatus = (state) => state.investigations.resumeStatus;
export const selectResumeError = (state) => state.investigations.resumeError;
// fetchPreviousInvestigation (D-05): { id, view, status, error }
export const selectPrevious = (state) => state.investigations.previous;

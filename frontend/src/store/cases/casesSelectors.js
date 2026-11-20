// [07c] Cases selectors — how pages and components read state.cases


// ═══════════════════════════════════════════════════════════════════
// 1. Case queue selectors — /cases
// ═══════════════════════════════════════════════════════════════════
export const selectCaseList = (state) => state.cases.list;
export const selectCaseListStatus = (state) => state.cases.listStatus;
export const selectCaseListError = (state) => state.cases.listError;


// ═══════════════════════════════════════════════════════════════════
// 2. One-case selectors — /cases/:caseId
// ═══════════════════════════════════════════════════════════════════
// state.cases.detail can still hold the previous case for a moment after the
// URL changes (until fetchCase.pending clears it), so this only returns it
// when it is the case being asked for.
// Usage: useSelector((state) => selectCaseDetail(state, caseId))
export const selectCaseDetail = (state, caseId) =>
  state.cases.detail?.case_id === caseId ? state.cases.detail : null;

export const selectCaseDetailStatus = (state) => state.cases.detailStatus;
export const selectCaseDetailError = (state) => state.cases.detailError;
export const selectCaseDetailNotFound = (state) => state.cases.detailNotFound;

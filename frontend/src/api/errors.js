// [03b] Error helpers — turn any axios error into ONE message string for the UI
// Used in every thunk's catch:  return rejectWithValue(getErrorMessage(err, 'Fallback'))
//
// Error bodies we handle (final format comes from the B-01 contracts in /docs):
//   {"detail": "Case not found"}                                   ← FastAPI HTTPException
//   {"detail": "Case not found", "code": "CASE_NOT_FOUND"}         ← if we add error codes
//   {"detail": [{"loc": ["body", "username"], "msg": "..."}]}      ← FastAPI 422 validation
// No err.response at all → network error / gateway or service down


// ═══════════════════════════════════════════════════════════════════
// 1. Friendly messages — by HTTP status, then by backend error code
// ═══════════════════════════════════════════════════════════════════
// Status messages are used only when the backend sends no readable `detail`.
// 403 matters here: a Viewer approving, or anyone opening another store's case.
const STATUS_MESSAGES = {
  401: 'Your session has expired. Please sign in again.',
  403: 'You do not have permission for this store or action.',
  404: 'Not found.',
  502: 'A backend service is unavailable. Please try again shortly.',
  503: 'A backend service is unavailable. Please try again shortly.',
  504: 'The request timed out. Please try again.',
};

// Fill in once the shared contracts (B-01) define error codes.
// Only override codes whose backend `detail` is too technical for an analyst.
const CODE_MESSAGES = {};


// ═══════════════════════════════════════════════════════════════════
// 2. getErrorMessage(err, fallback) → string
// ═══════════════════════════════════════════════════════════════════
export const getErrorMessage = (err, fallback = 'Something went wrong') => {
  // Step 1: no response → the request never reached the API
  if (!err?.response) {
    return 'Cannot reach the server. Please try again.';
  }

  const { status, data } = err.response;
  const { code, detail } = data?.error ?? data ?? {};

  // Step 2: known code → our wording
  if (code && CODE_MESSAGES[code]) return CODE_MESSAGES[code];
  if (typeof data?.error?.message === 'string') return data.error.message;

  // Step 3: FastAPI 422 → the first field error beats a generic message
  //   loc is e.g. ["body", "username"] → "username: Field required"
  if (Array.isArray(detail) && detail.length) {
    const { loc, msg } = detail[0];
    const field = loc?.[loc.length - 1];
    return field ? `${field}: ${msg}` : msg;
  }

  // Step 4: backend detail string → status message → caller's fallback
  if (typeof detail === 'string' && detail) return detail;
  return STATUS_MESSAGES[status] ?? fallback;
};

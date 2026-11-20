// [03b] Error helpers — turn any axios error into ONE message string for the UI
// Used in every thunk's catch:  return rejectWithValue(getErrorMessage(err, 'Fallback'))
//
// Error body (docs/contracts.md "Errors") — every service, including 422 validation:
//   { "error": { "code": "STALE_VERSION", "message": "...", "details": {...}, "request_id": "..." } }
// Legacy FastAPI bodies are still read as a fallback, in case a route slips through:
//   {"detail": "Case not found"}  ·  {"detail": [{"loc": ["body", "username"], "msg": "..."}]}
// No err.response at all → network error / gateway or service down


// ═══════════════════════════════════════════════════════════════════
// 1. Friendly messages — by backend error code, then by HTTP status
// ═══════════════════════════════════════════════════════════════════
// Codes from the contract's error table. Only codes whose backend message is
// too technical, or needs a next step for the analyst, are overridden here.
// Not listed on purpose — the backend message is more specific:
//   STALE_VERSION (names the current version), VALIDATION_ERROR (names the field),
//   INVALID_EVIDENCE / UNKNOWN_ACTION / SERVICE_TOKEN_INVALID (agent-only routes)
const CODE_MESSAGES = {
  // 401
  UNAUTHENTICATED: 'Your session has expired. Please sign in again.',
  INVALID_CREDENTIALS: 'Invalid username or password.',
  // 403 — a Viewer approving, or anyone touching another store
  FORBIDDEN: 'Your role cannot perform this action.',
  STORE_NOT_PERMITTED: 'You do not have access to this store.',
  // 404 — other stores' cases also come back as 404, so the wording covers both
  NOT_FOUND: 'Not found, or you do not have access to it.',
  CASE_NOT_FOUND: 'This case does not exist or you do not have access to it.',
  // 409 — someone (or an earlier click) got there first; refresh shows the latest
  INVESTIGATION_ACTIVE: 'This case already has an investigation in progress.',
  INVESTIGATION_FINISHED: 'This investigation has already finished. Refresh to see the result.',
  REOPEN_NOT_ALLOWED: 'This case cannot be reopened.',
  PROPOSAL_PENDING: 'This case already has a proposal waiting for a decision.',
  ALREADY_DECIDED: 'This proposal has already been decided. Refresh to see the latest status.',
  NOT_DISPATCHED: 'The merchant question has not been sent yet, so a reply cannot be recorded.',
  REPLY_EXISTS: 'A merchant reply has already been recorded for this question.',
  RECHECK_ALREADY_RUN: 'This recheck already has a result. Refresh to see it.',
  // 5xx
  DISPATCH_FAILED: 'The action could not be sent. The proposal is still pending — please try again.',
  UPSTREAM_UNAVAILABLE: 'A backend service is unavailable. Please try again shortly.',
  INTERNAL: 'Something went wrong on the server. Please try again.',
};

// Used only when the body has no code we know and no readable message
const STATUS_MESSAGES = {
  401: 'Your session has expired. Please sign in again.',
  403: 'You do not have permission for this store or action.',
  404: 'Not found.',
  502: 'A backend service is unavailable. Please try again shortly.',
  503: 'A backend service is unavailable. Please try again shortly.',
  504: 'The request timed out. Please try again.',
};


// ═══════════════════════════════════════════════════════════════════
// 2. getErrorCode(err) → contract code string, or null
// ═══════════════════════════════════════════════════════════════════
// For screens that react to a specific code, e.g. reload the proposal on
// STALE_VERSION instead of only showing a message.
export const getErrorCode = (err) => err?.response?.data?.error?.code ?? null;


// ═══════════════════════════════════════════════════════════════════
// 3. getErrorMessage(err, fallback) → string
// ═══════════════════════════════════════════════════════════════════
export const getErrorMessage = (err, fallback = 'Something went wrong') => {
  // Step 1: no response → the request never reached the API
  if (!err?.response) {
    return 'Cannot reach the server. Please try again.';
  }

  const { status, data } = err.response;
  const { code, message } = data?.error ?? {};

  // Step 2: known contract code → our wording
  if (code && CODE_MESSAGES[code]) return CODE_MESSAGES[code];

  // Step 3: contract envelope message
  if (typeof message === 'string' && message) return message;

  // Step 4: legacy FastAPI body — first field error, or the detail string
  //   loc is e.g. ["body", "username"] → "username: Field required"
  const detail = data?.detail;
  if (Array.isArray(detail) && detail.length) {
    const { loc, msg } = detail[0];
    const field = loc?.[loc.length - 1];
    return field ? `${field}: ${msg}` : msg;
  }
  if (typeof detail === 'string' && detail) return detail;

  // Step 5: status message → caller's fallback
  return STATUS_MESSAGES[status] ?? fallback;
};

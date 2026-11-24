// [07a] Cases thunks — async calls to /domain/cases (Domain Service, C-02)
// Always the real Domain API: it runs locally (see domain/README.md), and in dev
// the Vite proxy (vite.config.js) forwards /domain/* to it.
// With USE_MOCKS, the mock workflow's case state (status, proposals, rechecks —
// C-03/C-04, not built yet) is laid over the real response (mockInvestigations.js).


// ═══════════════════════════════════════════════════════════════════
// 1. Imports
// ═══════════════════════════════════════════════════════════════════
import { createAsyncThunk } from '@reduxjs/toolkit';
import api from '../../api/axios';
import { getErrorCode, getErrorMessage } from '../../api/errors';
import { USE_MOCKS } from '../../api/mockAuth';
import { applyMockCase, applyMockCaseList, mockCloseCase } from '../../api/mocks/mockInvestigations';
import { newUuid } from '../../utils/uuid';


// ═══════════════════════════════════════════════════════════════════
// 2. fetchCases — GET /domain/cases?status=&store_id=
// ═══════════════════════════════════════════════════════════════════
// → CaseSummary[], newest first. The backend already limits the list to the
// stores in the token, so the UI never filters by store grant itself.
// filters: { store_id, status } — an empty value means "all"
export const fetchCases = createAsyncThunk(
  'cases/fetchCases',
  async (filters = {}, { rejectWithValue }) => {
    // Drop empty filters so the URL only carries the ones the analyst picked
    const params = {};
    if (filters.store_id) params.store_id = filters.store_id;
    // Mocks change case status in the browser, so the status filter runs here
    if (filters.status && !USE_MOCKS) params.status = filters.status;

    try {
      const { data } = await api.get('/domain/cases', { params });
      if (!USE_MOCKS) return data;
      const list = applyMockCaseList(data);
      return filters.status ? list.filter((c) => c.status === filters.status) : list;
    } catch (err) {
      return rejectWithValue(getErrorMessage(err, 'Could not load cases'));
    }
  },
);


// ═══════════════════════════════════════════════════════════════════
// 3. fetchCase — GET /domain/cases/{case_id}
// ═══════════════════════════════════════════════════════════════════
// → CaseDetail: the CaseSummary fields plus store, daily_rates (42 days),
// investigation_ids, proposals and rechecks.
// Also re-run after an investigation starts or ends, because the Domain
// Service changes case.status when that happens (contracts.md "Status model").
//
// Rejects with { message, notFound }:
//   notFound = true on 404 / 403 — the case doesn't exist, or belongs to a store
//   this user can't see (Domain answers 404 for other stores' cases). Retrying
//   won't help, so the page shows "not found" instead of a Retry button.
export const fetchCase = createAsyncThunk(
  'cases/fetchCase',
  async (caseId, { rejectWithValue }) => {
    try {
      const { data } = await api.get(`/domain/cases/${caseId}`);
      return USE_MOCKS ? applyMockCase(data) : data;
    } catch (err) {
      const status = err.response?.status;
      return rejectWithValue({
        message: getErrorMessage(err, 'Could not load this case'),
        notFound: status === 404 || status === 403,
      });
    }
  },
);


// ═══════════════════════════════════════════════════════════════════
// 4. runMonitor — POST /domain/monitor/run (analyst only)
// ═══════════════════════════════════════════════════════════════════
// Demo trigger for the fixed-rule monitor: checks every store in the token and
// opens a case for each one over the threshold. The seed has no cases, so this
// is how the queue gets its first rows.
// → MonitorRunResponse { run_id, as_of, evaluated_store_ids, opened_case_ids,
//   skipped: [{ store_id, reason }] }
// No body: as_of defaults to the last day of data.
// One Idempotency-Key per click (contracts.md). The backend also never opens a
// second case for a store that already has one, so clicking again is safe.
// The caller reloads the queue afterwards (it knows the current filters).
export const runMonitor = createAsyncThunk(
  'cases/runMonitor',
  async (_, { rejectWithValue }) => {
    try {
      const { data } = await api.post('/domain/monitor/run', null, {
        headers: { 'Idempotency-Key': newUuid() },
      });
      return data;
    } catch (err) {
      return rejectWithValue(getErrorMessage(err, 'Could not run the monitor'));
    }
  },
);


// ═══════════════════════════════════════════════════════════════════
// 5. closeCase — POST /domain/cases/{case_id}/close (analyst only)
// ═══════════════════════════════════════════════════════════════════
// Empty body, Idempotency-Key. → 200 CaseSummary with status `closed`.
// Only from analyst_review: the action was rejected, the result was unsure, or
// the second fix didn't work, and the analyst has handled it.
// The case is reloaded either way: on 409 CASE_NOT_CLOSABLE it has moved on.
// Rejects with { message, code, noResponse }.
export const closeCase = createAsyncThunk(
  'cases/closeCase',
  async ({ caseId, idempotencyKey }, { getState, dispatch, rejectWithValue }) => {
    try {
      const summary = USE_MOCKS
        ? await mockCloseCase(caseId, { user: getState().auth.user, idempotencyKey })
        : (await api.post(`/domain/cases/${encodeURIComponent(caseId)}/close`, null, {
          headers: { 'Idempotency-Key': idempotencyKey },
        })).data;

      dispatch(fetchCase(caseId));
      return summary;
    } catch (err) {
      const code = getErrorCode(err);
      if (code === 'CASE_NOT_CLOSABLE') dispatch(fetchCase(caseId));
      return rejectWithValue({
        code,
        message: getErrorMessage(err, 'Could not close the case'),
        noResponse: !err?.response,
      });
    }
  },
);

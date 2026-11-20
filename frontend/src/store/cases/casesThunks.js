// [07a] Cases thunks — async calls to /domain/cases (Domain Service, C-02)
// No mock branch: the Domain API already runs locally (see domain/README.md),
// and in dev the Vite proxy (vite.config.js) forwards /domain/* to it.


// ═══════════════════════════════════════════════════════════════════
// 1. Imports
// ═══════════════════════════════════════════════════════════════════
import { createAsyncThunk } from '@reduxjs/toolkit';
import api from '../../api/axios';
import { getErrorMessage } from '../../api/errors';


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
    if (filters.status) params.status = filters.status;

    try {
      const { data } = await api.get('/domain/cases', { params });
      return data;
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
      return data;
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
        headers: { 'Idempotency-Key': crypto.randomUUID() },
      });
      return data;
    } catch (err) {
      return rejectWithValue(getErrorMessage(err, 'Could not run the monitor'));
    }
  },
);

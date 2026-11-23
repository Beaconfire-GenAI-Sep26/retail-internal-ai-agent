// [14a] Recheck thunks — POST /domain/rechecks/{id}/run (Domain Service, C-04)
// Normally Domain runs a recheck by itself on scheduled_for. For the demo the
// analyst runs it now ("Run recheck now").
// Mock branch when USE_MOCKS: C-04 hasn't built the route yet.
//
// The recheck itself is read from CaseDetail.rechecks; this slice only tracks
// the run request.


// ═══════════════════════════════════════════════════════════════════
// 1. Imports
// ═══════════════════════════════════════════════════════════════════
import { createAsyncThunk } from '@reduxjs/toolkit';
import api from '../../api/axios';
import { getErrorCode, getErrorMessage } from '../../api/errors';
import { USE_MOCKS } from '../../api/mockAuth';
import { mockRunRecheck } from '../../api/mocks/mockInvestigations';
import { fetchCase } from '../cases/casesThunks';


// ═══════════════════════════════════════════════════════════════════
// 2. runRecheck — POST /domain/rechecks/{recheck_id}/run
// ═══════════════════════════════════════════════════════════════════
// Empty body, Idempotency-Key. → 200 Recheck with its result.
// Domain then moves the case (contracts.md "Status model"):
//   improved → closed · insufficient_data → paused
//   not_improved → reopened the first time, analyst_review the second
// so the case is reloaded, which also brings back the recheck with its result.
//
// 409 RECHECK_ALREADY_RUN → it already has a result: reload the case to show it.
// Rejects with { message, code, noResponse }.
export const runRecheck = createAsyncThunk(
  'rechecks/run',
  async ({ id, caseId, idempotencyKey }, { getState, dispatch, rejectWithValue }) => {
    try {
      const recheck = USE_MOCKS
        ? await mockRunRecheck(id, { user: getState().auth.user, idempotencyKey })
        : (await api.post(`/domain/rechecks/${encodeURIComponent(id)}/run`, null, {
          headers: { 'Idempotency-Key': idempotencyKey },
        })).data;

      dispatch(fetchCase(caseId));
      return recheck;
    } catch (err) {
      const code = getErrorCode(err);
      if (code === 'RECHECK_ALREADY_RUN') dispatch(fetchCase(caseId));
      return rejectWithValue({
        code,
        message: getErrorMessage(err, 'Could not run the recheck'),
        noResponse: !err?.response,
      });
    }
  },
);

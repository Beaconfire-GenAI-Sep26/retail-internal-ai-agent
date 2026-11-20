// [15a] Audit thunks — GET /domain/cases/{case_id}/audit (Domain Service, C-03)
// Who did what to a case, and when. Mock branch when USE_MOCKS: C-03 hasn't
// built the route yet.


// ═══════════════════════════════════════════════════════════════════
// 1. Imports
// ═══════════════════════════════════════════════════════════════════
import { createAsyncThunk } from '@reduxjs/toolkit';
import api from '../../api/axios';
import { getErrorMessage } from '../../api/errors';
import { USE_MOCKS } from '../../api/mockAuth';
import { mockListAudit } from '../../api/mocks/mockInvestigations';


// ═══════════════════════════════════════════════════════════════════
// 2. fetchAudit — GET /domain/cases/{case_id}/audit
// ═══════════════════════════════════════════════════════════════════
// → AuditEntry[]. contracts.md doesn't fix the order (the mock sends oldest
// first), so the selector sorts newest first.
// The mock gets the case's opened_at so it can show the monitor's "case.opened" row.
export const fetchAudit = createAsyncThunk(
  'audit/fetch',
  async (caseId, { getState, rejectWithValue }) => {
    try {
      if (USE_MOCKS) {
        const detail = getState().cases.detail;
        const openedAt = detail?.case_id === caseId ? detail.opened_at : null;
        return await mockListAudit(caseId, { user: getState().auth.user, opened_at: openedAt });
      }
      const { data } = await api.get(`/domain/cases/${encodeURIComponent(caseId)}/audit`);
      return data;
    } catch (err) {
      return rejectWithValue(getErrorMessage(err, 'Could not load the activity'));
    }
  },
);

// [09a] Evidence thunks — GET /domain/evidence/{evidence_id} (Domain Service)
// Opens the record behind an evidence ID: a claim, a cancellation, an
// operational event or a merchant reply.
//
// Mock branch when USE_MOCKS: Domain already serves this route, but the mock
// investigations cite illustrative IDs that the real seed doesn't have, so the
// mock answers for them (d03 plan, "哪些走真实接口，哪些走 mock").


// ═══════════════════════════════════════════════════════════════════
// 1. Imports
// ═══════════════════════════════════════════════════════════════════
import { createAsyncThunk } from '@reduxjs/toolkit';
import api from '../../api/axios';
import { getErrorMessage } from '../../api/errors';
import { USE_MOCKS } from '../../api/mockAuth';
import { mockGetEvidence } from '../../api/mocks/mockInvestigations';


// ═══════════════════════════════════════════════════════════════════
// 2. fetchEvidence — GET /domain/evidence/{evidence_id}
// ═══════════════════════════════════════════════════════════════════
// → contract Evidence { evidence_id, type, store_id, occurred_at, summary, attributes }
// 404 also covers another store's evidence (contracts.md "Errors"), so the
// message says "not found, or you do not have access".
export const fetchEvidence = createAsyncThunk(
  'evidence/fetchOne',
  async (evidenceId, { getState, rejectWithValue }) => {
    try {
      if (USE_MOCKS) return await mockGetEvidence(evidenceId, { user: getState().auth.user });
      const { data } = await api.get(`/domain/evidence/${encodeURIComponent(evidenceId)}`);
      return data;
    } catch (err) {
      return rejectWithValue(getErrorMessage(err, 'Could not load this evidence'));
    }
  },
  {
    // Evidence records never change: fetch each ID once. A failed one can be retried.
    condition: (evidenceId, { getState }) => {
      const status = getState().evidence.statusById[evidenceId];
      return status !== 'loading' && status !== 'succeeded';
    },
  },
);

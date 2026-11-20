// [08a] Investigation thunks — async calls to /agent/investigations (Agent Service, B-02)
// Mock branch when USE_MOCKS (api/mocks/mockInvestigations.js, D-04), until the
// Agent Service runs locally. The mocks know CASE-0001 and CASE-0002, the same
// IDs the seeded Domain database opens.


// ═══════════════════════════════════════════════════════════════════
// 1. Imports
// ═══════════════════════════════════════════════════════════════════
import { createAsyncThunk } from '@reduxjs/toolkit';
import api from '../../api/axios';
import { getErrorMessage } from '../../api/errors';
import { USE_MOCKS } from '../../api/mockAuth';
import {
  mockListInvestigations,
  mockStartInvestigation,
  mockGetInvestigation,
} from '../../api/mocks/mockInvestigations';
import { fetchCase } from '../cases/casesThunks';

// Every thunk resolves to a contract InvestigationView (or null = never investigated):
//   { investigation_id, case_id, status, step_count, max_steps, started_by, error, ... }
// status: 'running' | 'awaiting_approval' | 'awaiting_merchant' | 'completed' | 'unsure' | 'failed'
//
// The mocks check role and store grants like the backend, so they need the
// logged-in user: getState().auth.user


// ═══════════════════════════════════════════════════════════════════
// 2. fetchLatestInvestigation — GET /agent/investigations?case_id=
// ═══════════════════════════════════════════════════════════════════
// Runs when the case page opens. The list comes back newest first, so [0] is the
// one to show. This also restores a running investigation after a page reload:
// the panel sees status 'running' and starts polling again.
export const fetchLatestInvestigation = createAsyncThunk(
  'investigations/fetchLatest',
  async (caseId, { getState, rejectWithValue }) => {
    try {
      if (USE_MOCKS) {
        const list = await mockListInvestigations(caseId, { user: getState().auth.user });
        return list[0] ?? null;
      }

      const { data } = await api.get('/agent/investigations', { params: { case_id: caseId } });
      return data[0] ?? null;
    } catch (err) {
      return rejectWithValue(getErrorMessage(err, 'Could not load the investigation'));
    }
  },
);


// ═══════════════════════════════════════════════════════════════════
// 3. startInvestigation — POST /agent/investigations
// ═══════════════════════════════════════════════════════════════════
// Analysts only (the backend answers 403 for a Viewer).
// Body: StartInvestigationRequest { case_id, reopen_of }
//   reopen_of stays null in D-02 — starting again after a recheck reopens
//   the case is D-05.
// → 202 InvestigationView with status 'running'; polling takes over from there.
export const startInvestigation = createAsyncThunk(
  'investigations/start',
  async (caseId, { getState, dispatch, rejectWithValue }) => {
    const body = { case_id: caseId, reopen_of: null };

    try {
      const view = USE_MOCKS
        ? await mockStartInvestigation(body, { user: getState().auth.user })
        : (await api.post('/agent/investigations', body)).data;

      // The case moves to 'investigating' → reload it so the header badge updates
      dispatch(fetchCase(caseId));
      return view;
    } catch (err) {
      // e.g. 409 INVESTIGATION_ACTIVE — errors.js already has the wording
      return rejectWithValue(getErrorMessage(err, 'Could not start the investigation'));
    }
  },
);


// ═══════════════════════════════════════════════════════════════════
// 4. fetchInvestigation — GET /agent/investigations/{investigation_id}
// ═══════════════════════════════════════════════════════════════════
// Called every 2 s by usePollInvestigation while the status is 'running'.
export const fetchInvestigation = createAsyncThunk(
  'investigations/fetchOne',
  async (investigationId, { getState, dispatch, rejectWithValue }) => {
    try {
      const view = USE_MOCKS
        ? await mockGetInvestigation(investigationId, { user: getState().auth.user })
        : (await api.get(`/agent/investigations/${investigationId}`)).data;

      // Stopped running (finished or paused) → the case status changed too
      if (view.status !== 'running') dispatch(fetchCase(view.case_id));
      return view;
    } catch (err) {
      return rejectWithValue(getErrorMessage(err, 'Could not refresh the investigation'));
    }
  },
  {
    // Skip this tick if the previous request hasn't come back yet, so a slow
    // network never stacks up requests. A skipped call dispatches nothing.
    condition: (_, { getState }) => !getState().investigations.polling,
  },
);

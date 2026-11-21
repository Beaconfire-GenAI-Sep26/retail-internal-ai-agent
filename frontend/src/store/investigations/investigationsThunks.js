// [08a] Investigation thunks — async calls to /agent/investigations (Agent Service, B-02)
// Mock branch when USE_MOCKS (api/mocks/mockInvestigations.js, D-04), until the
// Agent Service runs locally. The mocks pick a scenario by the case's store
// (STORE-A, STORE-B), whatever ID the seeded Domain database gave the case.


// ═══════════════════════════════════════════════════════════════════
// 1. Imports
// ═══════════════════════════════════════════════════════════════════
import { createAsyncThunk } from '@reduxjs/toolkit';
import api from '../../api/axios';
import { getErrorCode, getErrorDetails, getErrorMessage } from '../../api/errors';
import { ensureFreshToken } from '../auth/freshToken';
import { USE_MOCKS } from '../../api/mockAuth';
import {
  mockListInvestigations,
  mockStartInvestigation,
  mockGetInvestigation,
  mockResumeInvestigation,
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
// Arg: { caseId, reopenOf } → StartInvestigationRequest { case_id, reopen_of }
//   reopenOf: the last investigation_id when the case is 'reopened' (the fix
//   didn't work, step 7 → "Start new investigation"); null otherwise.
//   Known gap (d03 plan, "需要确认"): a failed second run leaves the case 'open',
//   so "Start again" sends null. The mock still treats it as the second run.
// → 202 InvestigationView with status 'running'; polling takes over from there.
//
// Before the request: a token with < 25 min left is refreshed (store/auth/freshToken.js).
// Refusals (ui-workflow.md v0.3 "When a call is refused"):
//   409 INVESTIGATION_ACTIVE  not an error: someone (or another tab) already
//                             started one → show that run instead; it polls if running
//   409 REOPEN_NOT_ALLOWED    the button was out of date → reload the case
export const startInvestigation = createAsyncThunk(
  'investigations/start',
  async ({ caseId, reopenOf = null }, { getState, dispatch, rejectWithValue }) => {
    const body = { case_id: caseId, reopen_of: reopenOf };
    const user = getState().auth.user;

    try {
      await ensureFreshToken({ getState, dispatch });
    } catch {
      return rejectWithValue('Your session expired. Please sign in again.');
    }

    try {
      const view = USE_MOCKS
        ? await mockStartInvestigation(body, { user })
        : (await api.post('/agent/investigations', body)).data;

      // The case moves to 'investigating' → reload it so the header badge updates
      dispatch(fetchCase(caseId));
      return view;
    } catch (err) {
      const code = getErrorCode(err);

      // Already running or paused: load that run and show it as if just started
      const activeId = getErrorDetails(err).investigation_id;
      if (code === 'INVESTIGATION_ACTIVE' && activeId) {
        try {
          const active = USE_MOCKS
            ? await mockGetInvestigation(activeId, { user })
            : (await api.get(`/agent/investigations/${encodeURIComponent(activeId)}`)).data;
          dispatch(fetchCase(caseId));
          return active;
        } catch {
          // fall through to the message below
        }
      }

      if (code === 'REOPEN_NOT_ALLOWED') {
        dispatch(fetchCase(caseId));
        return rejectWithValue("This case can't start another investigation. The page was out of date and has been refreshed.");
      }

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
      // 404: the agent restarted and the run is gone (runs live in its memory).
      // Stop polling (the slice drops the run) and reload the case, so the page
      // shows what Domain still has (getCaseView's no-run view).
      if (err?.response?.status === 404) {
        const { caseId } = getState().investigations;
        if (caseId) dispatch(fetchCase(caseId));
        return rejectWithValue({ lost: true });
      }
      return rejectWithValue(getErrorMessage(err, 'Could not refresh the investigation'));
    }
  },
  {
    // Skip this tick if the previous request hasn't come back yet, so a slow
    // network never stacks up requests. A skipped call dispatches nothing.
    condition: (_, { getState }) => !getState().investigations.polling,
  },
);


// ═══════════════════════════════════════════════════════════════════
// 5. resumeInvestigation — POST /agent/investigations/{id}/resume (D-05)
// ═══════════════════════════════════════════════════════════════════
// The frontend wakes a paused run; Domain never calls the agent. Always the
// second call of a pair (ui-workflow.md v0.3 "Decide first, then resume"):
//   question decided → resume · reply recorded → resume
// Empty body: the agent re-reads Domain. Header: Idempotency-Key.
// → 202 InvestigationView — 'running' (polling takes over) or 'awaiting_merchant'.
//
// Rejects with { message, code, noResponse }, like the proposal writes.
// 409 INVESTIGATION_FINISHED → the run already ended: reload it.
export const resumeInvestigation = createAsyncThunk(
  'investigations/resume',
  async ({ id, idempotencyKey }, { getState, dispatch, rejectWithValue }) => {
    try {
      const view = USE_MOCKS
        ? await mockResumeInvestigation(id, { user: getState().auth.user, idempotencyKey })
        : (await api.post(`/agent/investigations/${encodeURIComponent(id)}/resume`, null, {
          headers: { 'Idempotency-Key': idempotencyKey },
        })).data;

      // Running again, or now waiting for the merchant → the case status moved
      dispatch(fetchCase(view.case_id));
      return view;
    } catch (err) {
      const code = getErrorCode(err);
      if (code === 'INVESTIGATION_FINISHED') dispatch(fetchInvestigation(id));
      return rejectWithValue({
        code,
        message: getErrorMessage(err, "Couldn't continue the investigation"),
        noResponse: !err?.response,
      });
    }
  },
);


// ═══════════════════════════════════════════════════════════════════
// 6. fetchPreviousInvestigation — GET /agent/investigations/{reopen_of} (D-05)
// ═══════════════════════════════════════════════════════════════════
// A second run (reopen_of set) shows the first one folded above it (box 15):
// its cause, its action, and the recheck that didn't improve. It has ended,
// so it is loaded once, never polled.
export const fetchPreviousInvestigation = createAsyncThunk(
  'investigations/fetchPrevious',
  async (investigationId, { getState, rejectWithValue }) => {
    try {
      if (USE_MOCKS) return await mockGetInvestigation(investigationId, { user: getState().auth.user });
      const { data } = await api.get(`/agent/investigations/${encodeURIComponent(investigationId)}`);
      return data;
    } catch (err) {
      return rejectWithValue(getErrorMessage(err, 'Could not load the previous investigation'));
    }
  },
  {
    // Already loaded or loading for this ID → skip
    condition: (investigationId, { getState }) => {
      const { previous } = getState().investigations;
      return !(previous.id === investigationId && previous.status !== 'failed');
    },
  },
);

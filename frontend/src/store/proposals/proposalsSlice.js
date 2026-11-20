// [13b] Proposals slice — proposals by ID, plus the state of each one's edit / decision


// ═══════════════════════════════════════════════════════════════════
// 1. Imports
// ═══════════════════════════════════════════════════════════════════
import { createSlice } from '@reduxjs/toolkit';
import { fetchProposal, editProposal, decideProposal } from './proposalsThunks';
import { credentialsCleared } from '../auth/authSlice';
import { logout } from '../auth/authThunks';


// ═══════════════════════════════════════════════════════════════════
// 2. Initial state
// ═══════════════════════════════════════════════════════════════════
// By ID, not "the current one": a case page can show a question and an action
// at once (D-05), and the previous run's action (commit 7).
const initialState = {
  byId: {}, // proposal_id → contract Proposal (latest version seen)

  // fetchProposal
  fetchStatusById: {}, // → 'loading' | 'succeeded' | 'failed'
  fetchErrorById: {}, // → message

  // editProposal / decideProposal — one write at a time per proposal
  writeById: {}, // → { kind: 'edit' | 'decide', status: 'loading' | 'failed', error: { message, code, noResponse } | null }
};


// ═══════════════════════════════════════════════════════════════════
// 3. Slice
// ═══════════════════════════════════════════════════════════════════
const proposalsSlice = createSlice({
  name: 'proposals',
  initialState,

  // ── 3a. Sync reducers ────────────────────────────────────────────
  reducers: {
    // Dismiss the last write's error (e.g. Cancel on the edit form)
    proposalWriteCleared(state, action) {
      delete state.writeById[action.payload];
    },
  },

  // ── 3b. extraReducers ────────────────────────────────────────────
  extraReducers: (builder) => {
    const startWrite = (kind) => (state, action) => {
      state.writeById[action.meta.arg.id] = { kind, status: 'loading', error: null };
    };
    const writeDone = (state, action) => {
      state.byId[action.meta.arg.id] = action.payload;
      delete state.writeById[action.meta.arg.id];
    };
    const writeFailed = (kind) => (state, action) => {
      state.writeById[action.meta.arg.id] = {
        kind,
        status: 'failed',
        error: action.payload ?? { message: 'Something went wrong', code: null, noResponse: false },
      };
    };

    builder
      // fetchProposal
      .addCase(fetchProposal.pending, (state, action) => {
        state.fetchStatusById[action.meta.arg] = 'loading';
        delete state.fetchErrorById[action.meta.arg];
      })
      .addCase(fetchProposal.fulfilled, (state, action) => {
        state.fetchStatusById[action.meta.arg] = 'succeeded';
        state.byId[action.meta.arg] = action.payload;
      })
      .addCase(fetchProposal.rejected, (state, action) => {
        state.fetchStatusById[action.meta.arg] = 'failed';
        state.fetchErrorById[action.meta.arg] = action.payload ?? 'Could not load the proposal';
      })

      // editProposal — the response is the new version
      .addCase(editProposal.pending, startWrite('edit'))
      .addCase(editProposal.fulfilled, writeDone)
      .addCase(editProposal.rejected, writeFailed('edit'))

      // decideProposal — the response is the decided proposal (with dispatch on approve)
      .addCase(decideProposal.pending, startWrite('decide'))
      .addCase(decideProposal.fulfilled, writeDone)
      .addCase(decideProposal.rejected, writeFailed('decide'))

      // A different user must not see these
      .addCase(logout.pending, () => initialState)
      .addCase(credentialsCleared, () => initialState);
  },
});


// ═══════════════════════════════════════════════════════════════════
// 4. Export
// ═══════════════════════════════════════════════════════════════════
export const { proposalWriteCleared } = proposalsSlice.actions;
export default proposalsSlice.reducer;

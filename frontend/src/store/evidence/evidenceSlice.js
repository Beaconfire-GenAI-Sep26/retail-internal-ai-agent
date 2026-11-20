// [09b] Evidence slice — cached evidence records + which one the drawer shows


// ═══════════════════════════════════════════════════════════════════
// 1. Imports
// ═══════════════════════════════════════════════════════════════════
import { createSlice } from '@reduxjs/toolkit';
import { fetchEvidence } from './evidenceThunks';
import { credentialsCleared } from '../auth/authSlice';
import { logout } from '../auth/authThunks';


// ═══════════════════════════════════════════════════════════════════
// 2. Initial state
// ═══════════════════════════════════════════════════════════════════
// Cached by ID: the same evidence is cited by the result, several checks and
// the proposals, so each record is fetched once.
const initialState = {
  byId: {}, // evidence_id → contract Evidence
  statusById: {}, // evidence_id → 'loading' | 'succeeded' | 'failed'
  errorById: {}, // evidence_id → message, when 'failed'
  openId: null, // the evidence the drawer shows, or null = drawer closed
};


// ═══════════════════════════════════════════════════════════════════
// 3. Slice
// ═══════════════════════════════════════════════════════════════════
const evidenceSlice = createSlice({
  name: 'evidence',
  initialState,

  // ── 3a. Sync reducers — open / close the drawer ──────────────────
  // Opening only sets the ID; EvidenceDrawer then fetches it if it isn't cached.
  reducers: {
    openEvidence(state, action) {
      state.openId = action.payload;
    },
    closeEvidence(state) {
      state.openId = null;
    },
  },

  // ── 3b. extraReducers — fetchEvidence lifecycle + logout ─────────
  extraReducers: (builder) => {
    builder
      .addCase(fetchEvidence.pending, (state, action) => {
        state.statusById[action.meta.arg] = 'loading';
        delete state.errorById[action.meta.arg];
      })
      .addCase(fetchEvidence.fulfilled, (state, action) => {
        state.statusById[action.meta.arg] = 'succeeded';
        state.byId[action.meta.arg] = action.payload;
      })
      .addCase(fetchEvidence.rejected, (state, action) => {
        state.statusById[action.meta.arg] = 'failed';
        state.errorById[action.meta.arg] = action.payload ?? 'Could not load this evidence';
      })
      // The cache holds store data: a different user must not see it
      .addCase(logout.pending, () => initialState)
      .addCase(credentialsCleared, () => initialState);
  },
});


// ═══════════════════════════════════════════════════════════════════
// 4. Export — actions for components, reducer for store.js
// ═══════════════════════════════════════════════════════════════════
export const { openEvidence, closeEvidence } = evidenceSlice.actions;
export default evidenceSlice.reducer;

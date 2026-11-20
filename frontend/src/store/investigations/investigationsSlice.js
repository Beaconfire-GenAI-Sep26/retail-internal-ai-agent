// [08b] Investigations slice — the latest investigation of the open case


// ═══════════════════════════════════════════════════════════════════
// 1. Imports
// ═══════════════════════════════════════════════════════════════════
import { createSlice } from '@reduxjs/toolkit';
import {
  fetchLatestInvestigation,
  startInvestigation,
  fetchInvestigation,
} from './investigationsThunks';


// ═══════════════════════════════════════════════════════════════════
// 2. Initial state
// ═══════════════════════════════════════════════════════════════════
// Only one case page is open at a time, so the slice holds one investigation and
// remembers which case it belongs to.
const initialState = {
  caseId: null, // the case `current` belongs to
  current: null, // contract InvestigationView, or null = never investigated

  // fetchLatestInvestigation — on page open
  loadStatus: 'idle', // 'idle' | 'loading' | 'succeeded' | 'failed'
  loadError: null,

  // startInvestigation — the Start button
  startStatus: 'idle', // 'idle' | 'loading' | 'succeeded' | 'failed'
  startError: null,

  // fetchInvestigation — the 2 s poll
  polling: false, // a poll request is in flight (see the thunk's `condition`)
  pollError: null, // last poll failed; polling keeps trying
};


// ═══════════════════════════════════════════════════════════════════
// 3. Slice — thunk lifecycle only (no sync reducers yet)
// ═══════════════════════════════════════════════════════════════════
const investigationsSlice = createSlice({
  name: 'investigations',
  initialState,
  reducers: {},

  // ── 3a. extraReducers — pending / fulfilled / rejected per thunk ──
  extraReducers: (builder) => {
    builder
      // fetchLatestInvestigation — opening a case starts from a clean slate
      .addCase(fetchLatestInvestigation.pending, (state, action) => {
        return { ...initialState, caseId: action.meta.arg, loadStatus: 'loading' };
      })
      .addCase(fetchLatestInvestigation.fulfilled, (state, action) => {
        // Ignore a late answer for a case the analyst has already left
        if (action.meta.arg !== state.caseId) return;
        state.loadStatus = 'succeeded';
        state.current = action.payload;
      })
      .addCase(fetchLatestInvestigation.rejected, (state, action) => {
        if (action.meta.arg !== state.caseId) return;
        state.loadStatus = 'failed';
        state.loadError = action.payload ?? 'Could not load the investigation';
      })

      // startInvestigation
      .addCase(startInvestigation.pending, (state) => {
        state.startStatus = 'loading';
        state.startError = null;
      })
      .addCase(startInvestigation.fulfilled, (state, action) => {
        state.startStatus = 'succeeded';
        state.current = action.payload;
      })
      .addCase(startInvestigation.rejected, (state, action) => {
        state.startStatus = 'failed';
        state.startError = action.payload ?? 'Could not start the investigation';
      })

      // fetchInvestigation — the poll
      .addCase(fetchInvestigation.pending, (state) => {
        state.polling = true;
      })
      .addCase(fetchInvestigation.fulfilled, (state, action) => {
        state.polling = false;
        state.pollError = null;
        // Only update if it's still the investigation on screen
        if (action.payload.investigation_id === state.current?.investigation_id) {
          state.current = action.payload;
        }
      })
      .addCase(fetchInvestigation.rejected, (state, action) => {
        state.polling = false;
        state.pollError = action.payload ?? 'Could not refresh the investigation';
      });
  },
});


// ═══════════════════════════════════════════════════════════════════
// 4. Export — reducer for store.js
// ═══════════════════════════════════════════════════════════════════
export default investigationsSlice.reducer;

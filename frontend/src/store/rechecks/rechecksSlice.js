// [14b] Rechecks slice — the "run recheck" request per recheck
// The recheck data lives in CaseDetail.rechecks (cases slice). This only says
// whether a run is in flight or failed, so the button can show it.


// ═══════════════════════════════════════════════════════════════════
// 1. Imports
// ═══════════════════════════════════════════════════════════════════
import { createSlice } from '@reduxjs/toolkit';
import { runRecheck } from './rechecksThunks';


// ═══════════════════════════════════════════════════════════════════
// 2. Initial state
// ═══════════════════════════════════════════════════════════════════
const initialState = {
  runById: {}, // recheck_id → { status: 'loading' | 'failed', error: { message, code, noResponse } | null }
};


// ═══════════════════════════════════════════════════════════════════
// 3. Slice
// ═══════════════════════════════════════════════════════════════════
const rechecksSlice = createSlice({
  name: 'rechecks',
  initialState,
  reducers: {},
  extraReducers: (builder) => {
    builder
      .addCase(runRecheck.pending, (state, action) => {
        state.runById[action.meta.arg.id] = { status: 'loading', error: null };
      })
      // Done: the result arrives with the case reload
      .addCase(runRecheck.fulfilled, (state, action) => {
        delete state.runById[action.meta.arg.id];
      })
      .addCase(runRecheck.rejected, (state, action) => {
        state.runById[action.meta.arg.id] = {
          status: 'failed',
          error: action.payload ?? { message: 'Could not run the recheck', code: null, noResponse: false },
        };
      });
  },
});


// ═══════════════════════════════════════════════════════════════════
// 4. Export
// ═══════════════════════════════════════════════════════════════════
export default rechecksSlice.reducer;

// [07b] Cases slice — the case queue and the one case that is open


// ═══════════════════════════════════════════════════════════════════
// 1. Imports
// ═══════════════════════════════════════════════════════════════════
import { createSlice } from '@reduxjs/toolkit';
import { fetchCases, fetchCase } from './casesThunks';


// ═══════════════════════════════════════════════════════════════════
// 2. Initial state
// ═══════════════════════════════════════════════════════════════════
const initialState = {
  // ── Case queue — /cases ──
  list: [], // contract CaseSummary[]
  listStatus: 'idle', // 'idle' | 'loading' | 'succeeded' | 'failed'
  listError: null, // message shown above the table

  // ── One case — /cases/:caseId ──
  detail: null, // contract CaseDetail, or null before it loads
  detailStatus: 'idle', // 'idle' | 'loading' | 'succeeded' | 'failed'
  detailError: null, // message shown instead of the case
  detailNotFound: false, // 404 / 403 → "not found" page, no Retry
};


// ═══════════════════════════════════════════════════════════════════
// 3. Slice — thunk lifecycle only (no sync reducers yet)
// ═══════════════════════════════════════════════════════════════════
const casesSlice = createSlice({
  name: 'cases',
  initialState,
  reducers: {},

  // ── 3a. extraReducers — pending / fulfilled / rejected per thunk ──
  extraReducers: (builder) => {
    builder
      // fetchCases — the table keeps its old rows while a new filter loads
      .addCase(fetchCases.pending, (state) => {
        state.listStatus = 'loading';
        state.listError = null;
      })
      .addCase(fetchCases.fulfilled, (state, action) => {
        state.listStatus = 'succeeded';
        state.list = action.payload;
      })
      .addCase(fetchCases.rejected, (state, action) => {
        state.listStatus = 'failed';
        state.listError = action.payload ?? 'Could not load cases';
      })

      // fetchCase — two kinds of call:
      //   opening a different case → clear the old one and show "Loading…"
      //   refreshing the same case (after an investigation starts or ends)
      //     → keep showing it, so the page doesn't flash
      .addCase(fetchCase.pending, (state, action) => {
        const caseId = action.meta.arg;
        if (state.detail?.case_id !== caseId) {
          state.detail = null;
          state.detailStatus = 'loading';
        }
        state.detailError = null;
        state.detailNotFound = false;
      })
      .addCase(fetchCase.fulfilled, (state, action) => {
        state.detailStatus = 'succeeded';
        state.detail = action.payload;
      })
      .addCase(fetchCase.rejected, (state, action) => {
        state.detailStatus = 'failed';
        state.detail = null;
        state.detailError = action.payload?.message ?? 'Could not load this case';
        state.detailNotFound = action.payload?.notFound ?? false;
      });
  },
});


// ═══════════════════════════════════════════════════════════════════
// 4. Export — reducer for store.js
// ═══════════════════════════════════════════════════════════════════
export default casesSlice.reducer;

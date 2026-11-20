// [15b] Audit slice — the open case's activity log


// ═══════════════════════════════════════════════════════════════════
// 1. Imports
// ═══════════════════════════════════════════════════════════════════
import { createSlice } from '@reduxjs/toolkit';
import { fetchAudit } from './auditThunks';
import { credentialsCleared } from '../auth/authSlice';
import { logout } from '../auth/authThunks';


// ═══════════════════════════════════════════════════════════════════
// 2. Initial state
// ═══════════════════════════════════════════════════════════════════
// One case page at a time, like the investigations slice.
const initialState = {
  caseId: null, // the case `entries` belong to
  entries: [], // contract AuditEntry[], as the server sent them
  status: 'idle', // 'idle' | 'loading' | 'succeeded' | 'failed'
  error: null,
};


// ═══════════════════════════════════════════════════════════════════
// 3. Slice
// ═══════════════════════════════════════════════════════════════════
const auditSlice = createSlice({
  name: 'audit',
  initialState,
  reducers: {},
  extraReducers: (builder) => {
    builder
      // Refreshing the same case keeps the old rows on screen meanwhile;
      // another case starts empty.
      .addCase(fetchAudit.pending, (state, action) => {
        if (state.caseId !== action.meta.arg) {
          return { ...initialState, caseId: action.meta.arg, status: 'loading' };
        }
        state.status = 'loading';
        state.error = null;
        return undefined;
      })
      .addCase(fetchAudit.fulfilled, (state, action) => {
        if (state.caseId !== action.meta.arg) return;
        state.status = 'succeeded';
        state.entries = action.payload;
      })
      .addCase(fetchAudit.rejected, (state, action) => {
        if (state.caseId !== action.meta.arg) return;
        state.status = 'failed';
        state.error = action.payload ?? 'Could not load the activity';
      })
      .addCase(logout.pending, () => initialState)
      .addCase(credentialsCleared, () => initialState);
  },
});


// ═══════════════════════════════════════════════════════════════════
// 4. Export
// ═══════════════════════════════════════════════════════════════════
export default auditSlice.reducer;

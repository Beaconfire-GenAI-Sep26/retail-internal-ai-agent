// [08b] Monitor slice — cached store data for the Monitor dashboard (D-06)
//   base[storeId]   one entry per store (fetchStoreBase)
//   ranges[key]     one entry per store + date range (fetchStoreRange, key = rangeKey)
// Each entry: { status: 'loading' | 'succeeded' | 'failed', data, error }
// Nothing is cleared while the app runs: seed data doesn't change, and it lets
// the analyst flip between stores and ranges without waiting again.


// ═══════════════════════════════════════════════════════════════════
// 1. Imports
// ═══════════════════════════════════════════════════════════════════
import { createSlice } from '@reduxjs/toolkit';
import { fetchStoreBase, fetchStoreRange, rangeKey } from './monitorThunks';
import { logout } from '../auth/authThunks';


// ═══════════════════════════════════════════════════════════════════
// 2. Slice
// ═══════════════════════════════════════════════════════════════════
const initialState = { base: {}, ranges: {} };

// pending / fulfilled / rejected for one cache map
const track = (builder, thunk, map, keyOf) =>
  builder
    .addCase(thunk.pending, (state, action) => {
      state[map][keyOf(action.meta.arg)] = { status: 'loading', data: null, error: null };
    })
    .addCase(thunk.fulfilled, (state, action) => {
      state[map][keyOf(action.meta.arg)] = { status: 'succeeded', data: action.payload, error: null };
    })
    .addCase(thunk.rejected, (state, action) => {
      state[map][keyOf(action.meta.arg)] = {
        status: 'failed',
        data: null,
        error: action.payload ?? 'Could not load store data',
      };
    });

const monitorSlice = createSlice({
  name: 'monitor',
  initialState,
  reducers: {},
  extraReducers: (builder) => {
    track(builder, fetchStoreBase, 'base', (storeId) => storeId);
    track(builder, fetchStoreRange, 'ranges', (arg) => rangeKey(arg.storeId, arg));
    // Another user may have other store grants → drop everything on logout
    builder.addCase(logout.fulfilled, () => initialState);
  },
});


// ═══════════════════════════════════════════════════════════════════
// 3. Export — reducer for store.js
// ═══════════════════════════════════════════════════════════════════
export default monitorSlice.reducer;

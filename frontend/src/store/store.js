// [04] Redux store — one slice per feature
//
// State tree:
//   auth     who is logged in (role, store_ids) + access token   store/auth/
//   cases    (D-02) case queue · one case · evidence             store/cases/


// ═══════════════════════════════════════════════════════════════════
// 1. Imports
// ═══════════════════════════════════════════════════════════════════
import { configureStore } from '@reduxjs/toolkit';
import authReducer from './auth/authSlice';
import { injectStore } from '../api/axios';


// ═══════════════════════════════════════════════════════════════════
// 2. Store instance — one key per slice (see the state tree above)
// ═══════════════════════════════════════════════════════════════════
// configureStore combines the slice reducers into one root store and turns on
// Redux DevTools + the thunk middleware by default.
const store = configureStore({
  reducer: {
    auth: authReducer,
  },
});


// ═══════════════════════════════════════════════════════════════════
// 3. Hand the store to axios — interceptors need the token
// ═══════════════════════════════════════════════════════════════════
// Injected rather than imported in axios.js to avoid a circular import:
// store -> slices -> thunks -> axios -> store.
injectStore(store);


// ═══════════════════════════════════════════════════════════════════
// 4. Export
// ═══════════════════════════════════════════════════════════════════
export default store;

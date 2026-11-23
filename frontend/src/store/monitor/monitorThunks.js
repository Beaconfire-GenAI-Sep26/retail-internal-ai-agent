// [08a] Monitor thunks — store data for the Monitor dashboard (D-06)
// Only store and order data from /domain/stores/{id}/... — no case data.
// With USE_MOCKS the same calls go to api/mocks/mockStores.js instead.
//
// Two loads per store, both cached in the monitor slice:
//   fetchStoreBase   once per store: the 42-day daily series, events, names
//                    → trend chart + KPIs for any range (summed in the browser)
//   fetchStoreRange  once per store + date range: the breakdowns for that range
//                    → error categories, review status, dayparts, items, cancellations


// ═══════════════════════════════════════════════════════════════════
// 1. Imports
// ═══════════════════════════════════════════════════════════════════
import { createAsyncThunk } from '@reduxjs/toolkit';
import api from '../../api/axios';
import { getErrorMessage } from '../../api/errors';
import { toStoreDate } from '../../api/format';
import { USE_MOCKS } from '../../api/mockAuth';
import * as mock from '../../api/mocks/mockStores';
import {
  countsBy,
  dailyRows,
  parseClaimGroups,
  parseEvents,
  parseOverview,
} from '../../components/monitor/monitorMath';


// ═══════════════════════════════════════════════════════════════════
// 2. Endpoint calls — real API or mock, same bodies either way
// ═══════════════════════════════════════════════════════════════════
// ctx = { user } for the mock's store-grant check
const storeApi = (storeId, ctx) => {
  const base = `/domain/stores/${storeId}`;
  if (USE_MOCKS) {
    return {
      store: () => mock.mockGetStore(storeId, ctx),
      menu: () => mock.mockGetMenu(storeId, ctx),
      overview: (params) => mock.mockStoreOverview(storeId, params, ctx),
      events: (params) => mock.mockEventLog(storeId, params, ctx),
      claims: (body) => mock.mockClaimBreakdown(storeId, body, ctx),
      cancellations: (body) => mock.mockCancellationBreakdown(storeId, body, ctx),
    };
  }
  const get = (path, params) => api.get(`${base}${path}`, { params }).then((r) => r.data);
  const post = (path, body) => api.post(`${base}${path}`, body).then((r) => r.data);
  return {
    store: () => get(''),
    menu: () => get('/menu'),
    overview: (params) => get('/overview', params),
    events: (params) => get('/diagnostics/events', params),
    claims: (body) => post('/diagnostics/claim-breakdown', body),
    cancellations: (body) => post('/diagnostics/cancellation-breakdown', body),
  };
};


// ═══════════════════════════════════════════════════════════════════
// 3. fetchStoreBase(storeId)
// ═══════════════════════════════════════════════════════════════════
// overview with no dates = the 42 days ending on the store's last day of data.
// Its window gives the dates for the other calls, which then run in parallel.
// → { storeId, store, window, daily, cancelDaily, events, itemNames }
//     daily        [{ date, num: attributable claims, den: delivered orders }]
//     cancelDaily  [{ date, num: cancellations, den: placed orders }]
export const fetchStoreBase = createAsyncThunk(
  'monitor/fetchStoreBase',
  async (storeId, { getState, rejectWithValue }) => {
    const call = storeApi(storeId, { user: getState().auth.user });
    try {
      const overview = await call.overview();
      const { start, end } = overview.window;
      const [store, menu, events, cancelDays] = await Promise.all([
        call.store(),
        call.menu(),
        call.events({ start, end }),
        call.cancellations({ filter: { start, end }, group_by: 'day' }),
      ]);
      const toDate = (iso) => toStoreDate(iso, store.timezone);
      return {
        storeId,
        store,
        window: { start, end },
        daily: dailyRows(overview, 'daily_claim_rate'),
        cancelDaily: dailyRows(cancelDays, 'cancellation_rate'),
        events: parseEvents(events, toDate),
        itemNames: Object.fromEntries(menu.map((m) => [m.item_id, m.name])),
      };
    } catch (err) {
      return rejectWithValue(getErrorMessage(err, `Could not load ${storeId}`));
    }
  },
  // Loaded or loading already → skip (switching filters back is instant)
  { condition: (storeId, { getState }) => !getState().monitor.base[storeId]?.status?.match(/loading|succeeded/) },
);


// ═══════════════════════════════════════════════════════════════════
// 4. fetchStoreRange({ storeId, start, end })
// ═══════════════════════════════════════════════════════════════════
// Breakdowns that depend on the chosen range. Claim breakdowns use Domain's
// default review_label filter (store_fault + pending), the same "attributable"
// claims as the M&I rate.
// → { key, pendingClaims, errorCategories, reviewLabels, dayparts, items, modifiers, cancelCategories }
export const rangeKey = (storeId, { start, end }) => `${storeId}|${start}|${end}`;

export const fetchStoreRange = createAsyncThunk(
  'monitor/fetchStoreRange',
  async ({ storeId, start, end }, { getState, rejectWithValue }) => {
    const call = storeApi(storeId, { user: getState().auth.user });
    const filter = { start, end };
    try {
      const [overview, dayparts, items, modifiers, cancels] = await Promise.all([
        call.overview({ start, end }),
        call.claims({ filter, group_by: 'daypart' }),
        call.claims({ filter, group_by: 'item_id' }),
        call.claims({ filter, group_by: 'modifier' }),
        call.cancellations({ filter, group_by: 'cancellation_category' }),
      ]);
      const o = parseOverview(overview);
      return {
        key: rangeKey(storeId, filter),
        pendingClaims: o.pendingClaims,
        errorCategories: o.errorCategories,
        reviewLabels: o.reviewLabels,
        dayparts: parseClaimGroups(dayparts, 'daypart'),
        items: parseClaimGroups(items, 'item_id'),
        modifiers: parseClaimGroups(modifiers, 'modifier'),
        cancelCategories: countsBy(cancels, 'cancellation_count', 'cancellation_category'),
      };
    } catch (err) {
      return rejectWithValue(getErrorMessage(err, `Could not load ${storeId} for this range`));
    }
  },
  {
    condition: (arg, { getState }) =>
      !getState().monitor.ranges[rangeKey(arg.storeId, arg)]?.status?.match(/loading|succeeded/),
  },
);

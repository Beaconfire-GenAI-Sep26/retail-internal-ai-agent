// [06c] Mock Domain store endpoints for the Monitor dashboard (D-06)
// Used only when VITE_USE_MOCKS=true, so the dashboard works with no Domain API.
//
// Mirrors domain/app/routers/stores.py:
//   GET  /domain/stores/{id}                                  → mockGetStore
//   GET  /domain/stores/{id}/menu                             → mockGetMenu
//   GET  /domain/stores/{id}/overview?start&end               → mockStoreOverview
//   GET  /domain/stores/{id}/diagnostics/events?start&end     → mockEventLog
//   POST /domain/stores/{id}/diagnostics/claim-breakdown      → mockClaimBreakdown
//   POST /domain/stores/{id}/diagnostics/cancellation-breakdown → mockCancellationBreakdown
// Each resolves to the same body as the real endpoint, and rejects with an
// axios-like error carrying the contract error envelope (like mockInvestigations.js).
// The last argument is the request context { user }; store grants are checked.
//
// The rows are simulated, not copied: a seeded random generator replays the
// story of domain/scripts/reset_and_seed.py, so the charts look the same:
//   10/05–11/15, STORE-A ~60 orders/day, STORE-B ~70, base claim rate 1.4%
//   STORE-A  from 10/30 "Extra sauce" is not mapped → ingredient_error claims
//            out of stock 10/24–26 · a fraud cluster of 5 pending claims
//   STORE-B  from 11/3 large dinner orders lose a bag → missing_item claims
//            promo 11/3–9 (+30% orders) · Friday dinners "too busy"


// ═══════════════════════════════════════════════════════════════════
// 1. Helpers
// ═══════════════════════════════════════════════════════════════════
import { addDays, daysBetween } from '../../components/monitor/monitorMath';

const delay = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

const mockError = (status, code, message) => {
  const err = new Error(message);
  err.response = {
    status,
    data: { error: { code, message, details: null, request_id: `mock-${Date.now()}` } },
  };
  return err;
};

// Small seeded generator (mulberry32): the same rows on every load
const seeded = (seed) => () => {
  seed = (seed + 0x6d2b79f5) | 0;
  let t = Math.imul(seed ^ (seed >>> 15), 1 | seed);
  t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
  return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
};
const pickWeighted = (rnd, values, weights) => {
  let r = rnd() * weights.reduce((a, b) => a + b, 0);
  for (let i = 0; i < values.length; i += 1) {
    r -= weights[i];
    if (r <= 0) return values[i];
  }
  return values[values.length - 1];
};
const pick = (rnd, values) => values[Math.floor(rnd() * values.length)];

// Same as Domain's MIN_GROUP_ORDERS: a smaller group's rate is null
const MIN_GROUP_ORDERS = 30;
const ratio = (num, den, min = 1) => (den > 0 && den >= min ? Math.round((num / den) * 10000) / 10000 : null);
const rateMetric = (name, group, num, den) =>
  ({ name, group, value: ratio(num, den, MIN_GROUP_ORDERS), numerator: num, denominator: den, unit: 'rate' });
const countMetric = (name, group, n) =>
  ({ name, group, value: n, numerator: null, denominator: null, unit: 'count' });
const shareMetric = (name, group, num, den) =>
  ({ name, group, value: ratio(num, den), numerator: num, denominator: den, unit: 'share' });

const weekday = (ymd) => new Date(`${ymd}T00:00:00Z`).getUTCDay();
// A Chicago local time as UTC ISO (CST is UTC-6 across the whole mock range
// after Nov 1; CDT before). Precise enough for "which day" in the event lane.
const chicago = (ymd, hour) => {
  const offset = ymd < '2026-11-01' ? 5 : 6;
  return new Date(Date.UTC(+ymd.slice(0, 4), +ymd.slice(5, 7) - 1, +ymd.slice(8, 10), hour + offset)).toISOString();
};


// ═══════════════════════════════════════════════════════════════════
// 2. Stores, menus, events — same IDs and names as the Domain seed
// ═══════════════════════════════════════════════════════════════════
const FIRST_DAY = '2026-10-05';
const LAST_DAY = '2026-11-15';
const DAYS = daysBetween(FIRST_DAY, LAST_DAY);

const menu = (letter, rows) =>
  rows.map(([name, category], i) => ({ item_id: `ITEM-${letter}-${String(i + 1).padStart(3, '0')}`, name, category }));

const STORES = {
  'STORE-A': {
    seed: 1,
    summary: { store_id: 'STORE-A', name: 'Golden Wok Kitchen', city: 'Chicago', timezone: 'America/Chicago', cuisine: 'chinese' },
    perDay: 60,
    menu: menu('A', [
      ['Orange Chicken', 'entree'], ['Kung Pao Chicken', 'entree'], ['Beef and Broccoli', 'entree'],
      ['Sweet and Sour Pork', 'entree'], ['Mapo Tofu', 'entree'], ['Fried Rice', 'side'], ['Chow Mein', 'side'],
      ['Egg Rolls (2)', 'side'], ['Hot and Sour Soup', 'side'], ['Jasmine Tea', 'drink'],
      ['Bubble Milk Tea', 'drink'], ['Mango Pudding', 'dessert'],
    ]),
    events: [
      ['EV-EVT-000001', 'store_downtime', chicago('2026-10-20', 17), chicago('2026-10-20', 19), 'Store paused on DoorDash for about 2 hours (tablet offline).'],
      ['EV-EVT-000002', 'menu_change', chicago('2026-10-30', 10), null, 'Added paid modifier "Extra sauce" (+$0.99) to all entrees.'],
      ['EV-EVT-000003', 'menu_change', chicago('2026-10-30', 10), null, 'Renamed drink "Milk Tea" to "Bubble Milk Tea".'],
    ],
  },
  'STORE-B': {
    seed: 2,
    summary: { store_id: 'STORE-B', name: 'Lone Star Family Grill', city: 'Houston', timezone: 'America/Chicago', cuisine: 'american' },
    perDay: 70,
    menu: menu('B', [
      ['Classic Cheeseburger', 'entree'], ['BBQ Brisket Plate', 'entree'], ['Fried Chicken (3 pc)', 'entree'],
      ['Grilled Chicken Sandwich', 'entree'], ['Family Meal for 4', 'entree'], ['French Fries', 'side'],
      ['Mac and Cheese', 'side'], ['Coleslaw', 'side'], ['Onion Rings', 'side'], ['Lemonade', 'drink'],
      ['Iced Sweet Tea', 'drink'], ['Chocolate Shake', 'drink'], ['Pecan Pie Slice', 'dessert'], ['Brownie', 'dessert'],
    ]),
    events: [
      ['EV-EVT-000004', 'menu_change', chicago('2026-11-01', 9), null, 'Price change: "Pecan Pie Slice" from $4.49 to $4.99.'],
      ['EV-EVT-000005', 'promotion', chicago('2026-11-03', 0), chicago('2026-11-10', 0), 'Promotion: 20% off family meals (Nov 3-9).'],
    ],
  },
};


// ═══════════════════════════════════════════════════════════════════
// 3. Row generator — orders, claims, cancellations per store (cached)
// ═══════════════════════════════════════════════════════════════════
//   order        { date, daypart, items: [item_id], modifiers: [name], delivered }
//   claim        { date, daypart, order, item_id, modifier, error_category, review_label }
//   cancellation { date, daypart, order, item_id, cancellation_category }
const A_CAUSE = '2026-10-30';
const B_CAUSE = '2026-11-03';
const B_PROMO = ['2026-11-03', '2026-11-09'];
const A_OUT_OF_STOCK = ['2026-10-24', '2026-10-26'];
const BACKLOG_FROM = '2026-11-14'; // store_fault claims this late are often still pending
const BASE_CLAIM_RATE = 0.014;
const BASE_CANCEL_RATE = 0.012;
const CATEGORIES = ['missing_item', 'incorrect_item', 'ingredient_error', 'wrong_order'];
const CANCEL_CATEGORIES = ['item_out_of_stock', 'too_busy', 'menu_data_mismatch', 'pos_technical_error', 'other'];

const cache = new Map();

const generate = (storeId) => {
  if (cache.has(storeId)) return cache.get(storeId);
  const s = STORES[storeId];
  const rnd = seeded(s.seed * 7919);
  const entrees = s.menu.filter((m) => m.category === 'entree').map((m) => m.item_id);
  const allItems = s.menu.map((m) => m.item_id);
  const orders = [];
  const claims = [];
  const cancellations = [];

  const label = (date, faultChance) => {
    if (rnd() >= faultChance) return 'not_store_fault';
    return date >= BACKLOG_FROM && rnd() < 0.6 ? 'pending' : 'store_fault';
  };

  for (const date of DAYS) {
    const promo = storeId === 'STORE-B' && date >= B_PROMO[0] && date <= B_PROMO[1];
    const n = Math.round(s.perDay * (promo ? 1.3 : 1) * (0.85 + 0.3 * rnd()));
    for (let i = 0; i < n; i += 1) {
      const daypart = pickWeighted(rnd, ['lunch', 'dinner', 'late_night'], [40, 50, 10]);
      const lines = 1 + Math.floor(rnd() * 3);
      const items = [pick(rnd, entrees), ...Array.from({ length: lines - 1 }, () => pick(rnd, allItems))];
      const modifiers = [];
      const sauce = storeId === 'STORE-A' && date >= A_CAUSE && rnd() < 0.4;
      if (sauce) modifiers.push('Extra sauce');
      const order = { date, daypart, items, modifiers, delivered: true };
      orders.push(order);

      // Cancellations
      let cancel = null;
      if (storeId === 'STORE-A' && date >= A_OUT_OF_STOCK[0] && date <= A_OUT_OF_STOCK[1] && rnd() < 0.15) cancel = 'item_out_of_stock';
      else if (storeId === 'STORE-B' && weekday(date) === 5 && daypart === 'dinner' && rnd() < 0.12) cancel = 'too_busy';
      else if (rnd() < BASE_CANCEL_RATE) cancel = pickWeighted(rnd, CANCEL_CATEGORIES, [25, 30, 15, 10, 20]);
      if (cancel) {
        order.delivered = false;
        cancellations.push({ date, daypart, order, item_id: items[0], cancellation_category: cancel });
        continue;
      }

      // Scenario A: the Extra sauce modifier never reaches the kitchen ticket
      if (sauce && rnd() < 0.15) {
        claims.push({ date, daypart, order, item_id: items[0], modifier: 'Extra sauce',
          error_category: 'ingredient_error', review_label: label(date, 0.92) });
        continue;
      }
      // Scenario B: large dinner orders lose a whole bag
      if (storeId === 'STORE-B' && date >= B_CAUSE && daypart === 'dinner' && lines >= 2 && rnd() < 0.2) {
        claims.push({ date, daypart, order, item_id: items[0], modifier: null,
          error_category: 'missing_item', review_label: label(date, 0.9) });
        continue;
      }
      if (rnd() < BASE_CLAIM_RATE) {
        claims.push({ date, daypart, order, item_id: pick(rnd, items), modifier: null,
          error_category: pickWeighted(rnd, CATEGORIES, [45, 25, 20, 10]), review_label: label(date, 0.72) });
      }
    }
  }

  // Fraud cluster (STORE-A distractor): one customer, 5 pending "entire order" claims
  if (storeId === 'STORE-A') {
    const delivered = orders.filter((o) => o.delivered && o.daypart === 'dinner');
    ['2026-11-06', '2026-11-08', '2026-11-10', '2026-11-12', '2026-11-14'].forEach((date) => {
      const order = delivered.find((o) => o.date === date);
      if (order) claims.push({ date, daypart: 'dinner', order, item_id: null, modifier: null,
        error_category: 'missing_item', review_label: 'pending' });
    });
  }

  const rows = { orders, claims, cancellations };
  cache.set(storeId, rows);
  return rows;
};


// ═══════════════════════════════════════════════════════════════════
// 4. Request checks + the ToolResult envelope
// ═══════════════════════════════════════════════════════════════════
const ATTRIBUTABLE = ['store_fault', 'pending'];

// Same order of checks as Domain's store_context: grant first, then existence
const requireStore = (storeId, user) => {
  if (!user) throw mockError(401, 'UNAUTHENTICATED', 'Token missing, malformed or expired.');
  if (!user.store_ids?.includes(storeId)) throw mockError(403, 'STORE_NOT_PERMITTED', `No access to store ${storeId}.`);
  if (!STORES[storeId]) throw mockError(404, 'NOT_FOUND', `Store ${storeId} was not found.`);
  return STORES[storeId];
};

// Default window: the 42 days ending on the last day of data
const windowOf = (start, end) => {
  const e = end ?? LAST_DAY;
  const s = start ?? addDays(e, -41);
  if (s > e) throw mockError(422, 'VALIDATION_ERROR', 'start must be on or before end.');
  return { start: s < FIRST_DAY ? FIRST_DAY : s, end: e > LAST_DAY ? LAST_DAY : e };
};
const inWindow = (w) => (row) => row.date >= w.start && row.date <= w.end;

const toolResult = (tool, storeId, w, eligible, rest) => ({
  tool,
  store_id: storeId,
  window: w,
  eligible_orders: eligible,
  pending_claims: 0,
  data_sufficient: eligible >= MIN_GROUP_ORDERS,
  headline: '',
  metrics: [],
  evidence_ids: [],
  evidence: [],
  notes: ['Mock data (VITE_USE_MOCKS=true).'],
  ...rest,
});


// ═══════════════════════════════════════════════════════════════════
// 5. Mock endpoints
// ═══════════════════════════════════════════════════════════════════
// GET /domain/stores/{id} → StoreSummary
export const mockGetStore = async (storeId, { user } = {}) => {
  await delay(120);
  return { ...requireStore(storeId, user).summary };
};

// GET /domain/stores/{id}/menu → MenuItemOut[]
export const mockGetMenu = async (storeId, { user } = {}) => {
  await delay(120);
  return requireStore(storeId, user).menu.map((m) => ({ ...m, store_id: storeId, price: 0, available_modifiers: [] }));
};

// GET /domain/stores/{id}/overview → store_overview ToolResult
export const mockStoreOverview = async (storeId, { start, end } = {}, { user } = {}) => {
  await delay(180);
  requireStore(storeId, user);
  const w = windowOf(start, end);
  const { orders, claims } = generate(storeId);
  const delivered = orders.filter(inWindow(w)).filter((o) => o.delivered);
  const windowClaims = claims.filter(inWindow(w));
  const attributable = windowClaims.filter((c) => ATTRIBUTABLE.includes(c.review_label));

  const metrics = [rateMetric('claim_rate', null, attributable.length, delivered.length)];
  for (const l of ['store_fault', 'not_store_fault', 'fraud', 'pending']) {
    metrics.push(countMetric('claim_count', `review_label=${l}`, windowClaims.filter((c) => c.review_label === l).length));
  }
  for (const cat of CATEGORIES) {
    metrics.push(countMetric('claim_count', `error_category=${cat}`, attributable.filter((c) => c.error_category === cat).length));
  }
  for (const day of daysBetween(w.start, w.end)) {
    metrics.push(rateMetric('daily_claim_rate', `day=${day}`,
      attributable.filter((c) => c.date === day).length, delivered.filter((o) => o.date === day).length));
  }
  return toolResult('store_overview', storeId, w, delivered.length, {
    pending_claims: attributable.filter((c) => c.review_label === 'pending').length,
    metrics,
  });
};

// GET /domain/stores/{id}/diagnostics/events → event_log ToolResult (evidence only)
export const mockEventLog = async (storeId, { start, end } = {}, { user } = {}) => {
  await delay(150);
  const s = requireStore(storeId, user);
  const w = windowOf(start, end);
  const lo = `${w.start}T00:00:00Z`;
  const hi = `${addDays(w.end, 1)}T12:00:00Z`;
  const events = s.events.filter(([, , startedAt, endedAt]) => startedAt < hi && (!endedAt || endedAt >= lo));
  return toolResult('event_log', storeId, w, 0, {
    evidence_ids: events.map(([id]) => id),
    evidence: events.map(([id, type, startedAt, endedAt, description]) => ({
      evidence_id: id,
      type: 'operational_event',
      store_id: storeId,
      occurred_at: startedAt,
      summary: `${type}: ${description}`,
      attributes: { event_type: type, started_at: startedAt, ended_at: endedAt, description },
    })),
  });
};

// POST /domain/stores/{id}/diagnostics/claim-breakdown
//   body { filter: { start, end, review_label? }, group_by }
// Supports the groupings the dashboard uses: daypart · item_id · modifier · error_category · day
const claimGroups = {
  daypart: { claim: (c) => [c.daypart], order: (o) => [o.daypart] },
  item_id: { claim: (c) => [c.item_id ?? 'unknown'], order: (o) => [...new Set(o.items)] },
  modifier: { claim: (c) => (c.modifier ? [c.modifier] : []), order: (o) => o.modifiers },
  error_category: { claim: (c) => [c.error_category], order: null },
  day: { claim: (c) => [c.date], order: (o) => [o.date] },
};
export const mockClaimBreakdown = async (storeId, { filter, group_by: groupBy }, { user } = {}) => {
  await delay(180);
  requireStore(storeId, user);
  const g = claimGroups[groupBy];
  if (!g) throw mockError(422, 'VALIDATION_ERROR', `Mock does not support group_by=${groupBy}.`);
  const w = windowOf(filter.start, filter.end);
  const labels = filter.review_label ?? ATTRIBUTABLE;
  const { orders, claims } = generate(storeId);
  const delivered = orders.filter(inWindow(w)).filter((o) => o.delivered);
  const matching = claims.filter(inWindow(w)).filter((c) => labels.includes(c.review_label));

  const groupOrders = new Map();
  if (g.order) for (const o of delivered) for (const k of g.order(o)) groupOrders.set(k, (groupOrders.get(k) ?? 0) + 1);
  const groupClaims = new Map();
  for (const c of matching) for (const k of g.claim(c)) groupClaims.set(k, (groupClaims.get(k) ?? 0) + 1);

  const keys = [...new Set([...groupClaims.keys(), ...groupOrders.keys()])].sort();
  const metrics = keys.flatMap((k) => {
    const group = `${groupBy}=${k}`;
    const n = groupClaims.get(k) ?? 0;
    const den = g.order ? groupOrders.get(k) : delivered.length;
    return [
      k === 'unknown'
        ? { name: 'claim_rate', group, value: null, numerator: n, denominator: null, unit: 'rate' }
        : rateMetric('claim_rate', group, n, den ?? 0),
      shareMetric('claim_share', group, n, matching.length),
    ];
  });
  return toolResult('claim_breakdown', storeId, w, delivered.length, { metrics });
};

// POST /domain/stores/{id}/diagnostics/cancellation-breakdown
//   body { filter: { start, end }, group_by }  — cancellation_category · daypart · day
const cancelGroups = {
  cancellation_category: { x: (x) => x.cancellation_category, order: null },
  daypart: { x: (x) => x.daypart, order: (o) => o.daypart },
  day: { x: (x) => x.date, order: (o) => o.date },
};
export const mockCancellationBreakdown = async (storeId, { filter, group_by: groupBy }, { user } = {}) => {
  await delay(160);
  requireStore(storeId, user);
  const g = cancelGroups[groupBy];
  if (!g) throw mockError(422, 'VALIDATION_ERROR', `Mock does not support group_by=${groupBy}.`);
  const w = windowOf(filter.start, filter.end);
  const { orders, cancellations } = generate(storeId);
  const placed = orders.filter(inWindow(w));
  const cxl = cancellations.filter(inWindow(w));

  const groupPlaced = new Map();
  if (g.order) for (const o of placed) groupPlaced.set(g.order(o), (groupPlaced.get(g.order(o)) ?? 0) + 1);
  const groupCxl = new Map();
  for (const x of cxl) groupCxl.set(g.x(x), (groupCxl.get(g.x(x)) ?? 0) + 1);

  const keys = [...new Set([...groupCxl.keys(), ...groupPlaced.keys()])].sort();
  const metrics = keys.flatMap((k) => {
    const group = `${groupBy}=${k}`;
    const n = groupCxl.get(k) ?? 0;
    return [
      rateMetric('cancellation_rate', group, n, g.order ? groupPlaced.get(k) ?? 0 : placed.length),
      countMetric('cancellation_count', group, n),
    ];
  });
  return toolResult('cancellation_breakdown', storeId, w, placed.filter((o) => o.delivered).length, { metrics });
};

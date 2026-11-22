// [14a] Monitor math — pure helpers for the Monitor dashboard (D-06)
// Turns Domain ToolResults into plain rows, and does the date and rate math the
// page needs. No React, no Redux, so every function is unit-tested on its own.
//
// Dates are store-local 'YYYY-MM-DD' strings (Domain already returns them that
// way), so the math is plain UTC arithmetic and no time zone can shift a day.


// ═══════════════════════════════════════════════════════════════════
// 1. Constants
// ═══════════════════════════════════════════════════════════════════
// Same default as Domain's MONITOR_GOAL_RATE (domain/app/settings.py). The store
// endpoints don't return it, and the dashboard stays off case data on purpose.
export const GOAL_RATE = 0.05;

// Store filter value for "compare every granted store"
export const ALL_STORES = 'ALL';

// Time range buttons, in days. The default compares two weeks with the two before.
export const RANGE_OPTIONS = [42, 14, 7];
export const DEFAULT_RANGE = 14;

// 7-day rolling is the window the monitor rule checks ("7-day rate above goal")
export const SMOOTH_OPTIONS = [7, 1];
export const DEFAULT_SMOOTH = 7;

// One color per store, in the order of the user's store grants. A store keeps
// its color in every view, so switching to one store never repaints it.
export const STORE_COLORS = ['var(--series-1)', 'var(--series-2)', 'var(--series-3)'];
export const storeColor = (storeIds, storeId) =>
  STORE_COLORS[Math.max(0, storeIds.indexOf(storeId)) % STORE_COLORS.length];


// ═══════════════════════════════════════════════════════════════════
// 2. Dates
// ═══════════════════════════════════════════════════════════════════
// '2026-10-30' + 3 → '2026-11-02'
export const addDays = (ymd, n) => {
  const d = new Date(`${ymd}T00:00:00Z`);
  d.setUTCDate(d.getUTCDate() + n);
  return d.toISOString().slice(0, 10);
};

// Every day from start to end, inclusive
export const daysBetween = (start, end) => {
  const days = [];
  for (let d = start; d <= end; d = addDays(d, 1)) days.push(d);
  return days;
};

// The last `days` days ending on `end` (the store's last day of data), never
// before `first`. → { start, end }
export const rangeWindow = (first, end, days) => {
  const start = addDays(end, -(days - 1));
  return { start: start < first ? first : start, end };
};

// The same number of days right before `current`, or null when that period
// starts before the data does (e.g. the full 42-day range).
export const previousWindow = (first, current, days) => {
  const end = addDays(current.start, -1);
  const start = addDays(end, -(days - 1));
  return start < first ? null : { start, end };
};

// '2026-11-03' → '11/3'
export const shortDay = (ymd) => `${Number(ymd.slice(5, 7))}/${Number(ymd.slice(8, 10))}`;


// ═══════════════════════════════════════════════════════════════════
// 3. Rates
// ═══════════════════════════════════════════════════════════════════
// No orders → null, shown as "Not enough data" (format.formatRate), never 0%
export const rate = (num, den) => (den > 0 ? num / den : null);

// Sum the day rows inside [start, end] → { num, den, rate }
//   rows: [{ date, num, den }]
export const sumWindow = (rows, { start, end }) => {
  let num = 0;
  let den = 0;
  for (const r of rows) {
    if (r.date >= start && r.date <= end) {
      num += r.num;
      den += r.den;
    }
  }
  return { num, den, rate: rate(num, den) };
};

// Trailing `size`-day rate for each row (size 1 = the daily rate). Days before
// the first row are missing, so the first rows average over fewer days.
//   rows: [{ date, num, den }] oldest first → [{ date, num, den, rate }]
export const rolling = (rows, size) =>
  rows.map((_, i) => {
    let num = 0;
    let den = 0;
    for (let j = Math.max(0, i - size + 1); j <= i; j += 1) {
      num += rows[j].num;
      den += rows[j].den;
    }
    return { date: rows[i].date, num, den, rate: rate(num, den) };
  });

// Change from the previous period, for the KPI arrows.
//   kind 'pt'  → difference in percentage points (rates)
//   kind 'pct' → relative change in % (counts)
// → { diff, text } or null when there is nothing to compare
export const delta = (current, previous, kind) => {
  if (current == null || previous == null) return null;
  if (kind === 'pt') {
    const diff = (current - previous) * 100;
    return { diff, text: `${Math.abs(diff).toFixed(1)}pt` };
  }
  if (!previous) return null;
  const diff = ((current - previous) / previous) * 100;
  return { diff, text: `${Math.abs(diff).toFixed(0)}%` };
};


// ═══════════════════════════════════════════════════════════════════
// 4. ToolResult parsing — Domain metrics → plain rows
// ═══════════════════════════════════════════════════════════════════
// A Metric is { name, group, value, numerator, denominator, unit }, and group
// reads "<dimension>=<value>", e.g. "day=2026-10-30" or "daypart=dinner".

// The metrics called `name` whose group is "<dimension>=…" → Map(value → metric)
export const metricsBy = (result, name, dimension) => {
  const prefix = `${dimension}=`;
  const out = new Map();
  for (const m of result?.metrics ?? []) {
    if (m.name === name && m.group?.startsWith(prefix)) out.set(m.group.slice(prefix.length), m);
  }
  return out;
};

// daily_claim_rate / cancellation_rate per day → [{ date, num, den }] oldest first
export const dailyRows = (result, name) =>
  [...metricsBy(result, name, 'day').entries()]
    .map(([date, m]) => ({ date, num: m.numerator ?? 0, den: m.denominator ?? 0 }))
    .sort((a, b) => (a.date < b.date ? -1 : 1));

// count metrics → { value: count }
export const countsBy = (result, name, dimension) =>
  Object.fromEntries([...metricsBy(result, name, dimension)].map(([k, m]) => [k, m.value ?? 0]));

// store_overview → what the dashboard keeps from it
export const parseOverview = (result) => ({
  window: result.window,
  pendingClaims: result.pending_claims,
  daily: dailyRows(result, 'daily_claim_rate'),
  errorCategories: countsBy(result, 'claim_count', 'error_category'),
  reviewLabels: countsBy(result, 'claim_count', 'review_label'),
});

// claim_breakdown → [{ key, claims, orders }] (orders is null for "unknown")
export const parseClaimGroups = (result, dimension) =>
  [...metricsBy(result, 'claim_rate', dimension)].map(([key, m]) => ({
    key,
    claims: m.numerator ?? 0,
    orders: m.denominator,
  }));

// event_log evidence → [{ id, date, endDate, type, description }], dates store-local
//   toDate: (isoTimestamp) → 'YYYY-MM-DD' in the store's time zone
// ended_at is exclusive (a promo "Nov 3–9" ends Nov 10 00:00), so endDate is the
// day of the last second before it.
const lastSecondBefore = (iso) => new Date(Date.parse(iso) - 1000).toISOString();
export const parseEvents = (result, toDate) =>
  (result?.evidence ?? []).map((e) => ({
    id: e.evidence_id,
    date: toDate(e.attributes.started_at ?? e.occurred_at),
    endDate: e.attributes.ended_at ? toDate(lastSecondBefore(e.attributes.ended_at)) : null,
    type: e.attributes.event_type,
    description: e.attributes.description,
  }));

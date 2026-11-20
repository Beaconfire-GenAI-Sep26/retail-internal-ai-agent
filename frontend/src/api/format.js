// [03d] Display helpers — rates, dates and enum labels, shown the same way on every page
// Display rules (docs/ui-workflow.md "What the UI shows"):
//   - rate: null shows "Not enough data", never "0%"
//   - rates show their sample size, e.g. "37 / 450"
//   - timestamps show in the store's timezone


// ═══════════════════════════════════════════════════════════════════
// 1. Rates — decimals from 0 to 1 (contracts.md "Conventions")
// ═══════════════════════════════════════════════════════════════════
// 0.0822 → "8.2%" · null → "Not enough data"
export const formatRate = (rate) =>
  rate == null ? 'Not enough data' : `${(rate * 100).toFixed(1)}%`;

// The sample size behind a rate: 37, 450 → "37 / 450"
export const formatRatio = (numerator, denominator) => `${numerator} / ${denominator}`;


// ═══════════════════════════════════════════════════════════════════
// 2. Dates — always in the store's timezone
// ═══════════════════════════════════════════════════════════════════
// Timestamps arrive in UTC (e.g. window_end "2026-11-16T05:59:59Z"). Shown in the
// browser's timezone they could land on the wrong day, so every timestamp is
// formatted with the store's IANA timezone (StoreSummary.timezone).

// "2026-11-09T06:00:00Z", "America/Chicago" → "Nov 9, 2026"
export const formatDate = (iso, timeZone) =>
  new Date(iso).toLocaleDateString('en-US', {
    timeZone,
    month: 'short',
    day: 'numeric',
    year: 'numeric',
  });

// window_start, window_end → "Nov 9 – Nov 15, 2026"
export const formatDateRange = (startIso, endIso, timeZone) => {
  const start = new Date(startIso).toLocaleDateString('en-US', {
    timeZone,
    month: 'short',
    day: 'numeric',
  });
  return `${start} – ${formatDate(endIso, timeZone)}`;
};

// Timestamp → the store-local date as "YYYY-MM-DD", the same format as
// CaseDetail.daily_rates[].date, so the two can be compared as strings.
// 'en-CA' is used only because it writes dates as YYYY-MM-DD.
export const toStoreDate = (iso, timeZone) =>
  new Date(iso).toLocaleDateString('en-CA', { timeZone });


// ═══════════════════════════════════════════════════════════════════
// 3. Enum labels — contract values → words for the analyst
// ═══════════════════════════════════════════════════════════════════
// case_status (contracts.md "Status model"), in workflow order — also the
// options of the status filter on the case queue
export const CASE_STATUS_LABELS = {
  open: 'Open',
  investigating: 'Investigating',
  awaiting_decision: 'Awaiting decision',
  awaiting_merchant: 'Awaiting merchant',
  action_dispatched: 'Action dispatched',
  analyst_review: 'Analyst review',
  reopened: 'Reopened',
  paused: 'Paused',
  closed: 'Closed',
};

// CaseSummary.trigger_rule — why the monitor opened the case
export const TRIGGER_LABELS = {
  over_goal: 'Over goal',
  spike_vs_baseline: 'Spike vs baseline',
};

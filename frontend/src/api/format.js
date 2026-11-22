// [03d] Display helpers — rates, dates and enum labels, shown the same way on every page
// Display rules (docs/ui-workflow.md "What the UI shows"):
//   - rate: null shows "Not enough data", never "0%"
//   - rates show their sample size, e.g. "37 / 450"
//   - timestamps show in the store's timezone
//   - enum values show as words; an unknown value shows as-is (labelOf)


// ═══════════════════════════════════════════════════════════════════
// 1. Rates — decimals from 0 to 1 (contracts.md "Conventions")
// ═══════════════════════════════════════════════════════════════════
// 0.0822 → "8.2%" · null → "Not enough data"
export const formatRate = (rate) =>
  rate == null ? 'Not enough data' : `${(rate * 100).toFixed(1)}%`;

// The sample size behind a rate: 37, 450 → "37 / 450"
export const formatRatio = (numerator, denominator) => `${numerator} / ${denominator}`;

// A contract RateWindow { claims, eligible_orders, rate } → rate with its sample size
//   { 12, 240, 0.05 } → "12 / 240 (5.0%)"
//   { 3, 40, null }   → "3 / 40 · Not enough data" (the sample size still shows)
export const formatRateWindow = (w) => {
  const ratio = formatRatio(w.claims, w.eligible_orders);
  return w.rate == null ? `${ratio} · Not enough data` : `${ratio} (${formatRate(w.rate)})`;
};


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

// A plain date with no time, e.g. InvestigationResult.cause_started_at "2026-10-30".
// It is already a store-local date, so it must NOT go through a timezone:
// new Date('2026-10-30') is UTC midnight, which is Oct 29 in Chicago.
// "2026-10-30" → "Oct 30, 2026" · null → "—"
export const formatDay = (ymd) => {
  if (!ymd) return '—';
  return new Date(`${ymd}T00:00:00Z`).toLocaleDateString('en-US', {
    timeZone: 'UTC',
    month: 'short',
    day: 'numeric',
    year: 'numeric',
  });
};

// Two plain dates, e.g. a RateWindow's start and end
// "2026-11-03", "2026-11-15" → "Nov 3 – Nov 15, 2026"
// "2026-12-28", "2027-01-05" → "Dec 28, 2026 – Jan 5, 2027" (years differ, both shown)
export const formatDayRange = (startYmd, endYmd) => {
  if (!startYmd || !endYmd) return '—';
  const end = formatDay(endYmd);
  if (startYmd.slice(0, 4) !== endYmd.slice(0, 4)) return `${formatDay(startYmd)} – ${end}`;
  const start = new Date(`${startYmd}T00:00:00Z`).toLocaleDateString('en-US', {
    timeZone: 'UTC',
    month: 'short',
    day: 'numeric',
  });
  return `${start} – ${end}`;
};

// Date and time, e.g. for evidence and the audit log
// "2026-11-04T01:12:00Z", "America/Chicago" → "Nov 3, 2026, 7:12 PM CST" · null → "—"
// Newer ICU puts a narrow no-break space before AM/PM; a plain space keeps it
// copy-pasteable and testable.
export const formatDateTime = (iso, timeZone) => {
  if (!iso) return '—';
  return new Date(iso)
    .toLocaleString('en-US', {
      timeZone,
      month: 'short',
      day: 'numeric',
      year: 'numeric',
      hour: 'numeric',
      minute: '2-digit',
      timeZoneName: 'short',
    })
    .replace(/ /g, ' ');
};

// Short date and time for narrow places (the audit sidebar). No year, no zone name:
// the full value goes in a tooltip.
// "2026-11-16T15:00:00Z", "America/Chicago" → "Nov 16, 9:00 AM"
export const formatDateTimeShort = (iso, timeZone) => {
  if (!iso) return '—';
  return new Date(iso)
    .toLocaleString('en-US', { timeZone, month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' })
    .replace(/ /g, ' ');
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

// Any enum label map → the label, or the raw value if the map doesn't know it
// (a new backend value still shows instead of disappearing).
// labelOf(CAUSE_LABELS, 'packing') → "Packing"
export const labelOf = (labels, value) => labels[value] ?? value;

// cause_category — InvestigationResult, Hypothesis, ruled_out[]
export const CAUSE_LABELS = {
  pos_modifier_mapping: 'POS modifier mapping',
  menu_change: 'Menu change',
  packing: 'Packing',
  inventory: 'Inventory',
  dasher_handoff: 'Dasher handoff',
  fraud_cluster: 'Fraud cluster',
  other: 'Other',
};

// confidence — the result badge
export const CONFIDENCE_LABELS = {
  low: 'Low confidence',
  medium: 'Medium confidence',
  high: 'High confidence',
};

// hypothesis_status — tag on each possible cause
export const HYPOTHESIS_STATUS_LABELS = {
  open: 'Open',
  supported: 'Supported',
  ruled_out: 'Ruled out',
  inconclusive: 'Inconclusive',
};

// check_kind — tag on each check
export const CHECK_KIND_LABELS = {
  explore: 'Explore',
  test: 'Test',
  challenge: 'Challenge',
};

// tool_name — which diagnostic a check ran
export const TOOL_LABELS = {
  store_overview: 'Store overview',
  event_log: 'Event log',
  claim_breakdown: 'Claim breakdown',
  compare_periods: 'Compare periods',
  sample_evidence: 'Evidence sample',
  cancellation_breakdown: 'Cancellation breakdown',
  fraud_signals: 'Fraud signals',
  merchant_replies: 'Merchant replies',
  action_catalog: 'Action catalog',
};

// owner_team — who an action is sent to
export const OWNER_TEAM_LABELS = {
  merchant: 'Merchant',
  pos_team: 'POS team',
  menu_team: 'Menu team',
  dasher_ops: 'Dasher ops',
  fraud_review: 'Fraud review',
  analyst: 'Analyst',
};

// recheck_status — "Did the fix work?"
export const RECHECK_STATUS_LABELS = {
  scheduled: 'Scheduled',
  improved: 'Improved',
  not_improved: 'Not improved',
  insufficient_data: 'Not enough data',
};


// ═══════════════════════════════════════════════════════════════════
// 4. Evidence labels — the evidence drawer
// ═══════════════════════════════════════════════════════════════════
// evidence_type
export const EVIDENCE_TYPE_LABELS = {
  claim: 'Claim',
  cancellation: 'Cancellation',
  operational_event: 'Operational event',
  merchant_reply: 'Merchant reply',
};

// ClaimAttributes.error_category
export const ERROR_CATEGORY_LABELS = {
  missing_item: 'Missing item',
  incorrect_item: 'Incorrect item',
  ingredient_error: 'Ingredient error',
  wrong_order: 'Wrong order',
};

// ClaimAttributes.review_label
export const REVIEW_LABEL_LABELS = {
  store_fault: 'Store fault',
  not_store_fault: 'Not store fault',
  fraud: 'Fraud',
  pending: 'Pending review',
};

// CancellationAttributes.cancellation_category
export const CANCELLATION_CATEGORY_LABELS = {
  item_out_of_stock: 'Item out of stock',
  too_busy: 'Too busy',
  menu_data_mismatch: 'Menu data mismatch',
  pos_technical_error: 'POS technical error',
  other: 'Other',
};

// EventAttributes.event_type
export const EVENT_TYPE_LABELS = {
  menu_change: 'Menu change',
  pos_change: 'POS change',
  store_downtime: 'Store downtime',
  promotion: 'Promotion',
};

// daypart — claims, cancellations, Target
export const DAYPART_LABELS = {
  breakfast: 'Breakfast',
  lunch: 'Lunch',
  dinner: 'Dinner',
  late_night: 'Late night',
};

// ReplyAttributes.outcome / MerchantReply.outcome
export const REPLY_OUTCOME_LABELS = {
  replied: 'Replied',
  no_reply: 'No reply',
};

// ClaimAttributes.error_charge: 1.5 → "$1.50"
export const formatMoney = (amount) => `$${Number(amount).toFixed(2)}`;


// ═══════════════════════════════════════════════════════════════════
// 5. Target — which orders an action and its recheck cover
// ═══════════════════════════════════════════════════════════════════
// Target { daypart[], item_count_min, item_id[], modifiers[] }, joined with " · "
//   { daypart: ['dinner'], item_count_min: 5, item_id: [], modifiers: ['Extra sauce'] }
//     → "dinner · 5+ items · Extra sauce"
//   nothing set → "All orders"
// Item IDs show as IDs: the Target carries no names.
export const formatTarget = (t) => {
  const parts = [
    ...(t.daypart ?? []).map((d) => labelOf(DAYPART_LABELS, d).toLowerCase()),
    t.item_count_min != null ? `${t.item_count_min}+ items` : null,
    ...(t.item_id ?? []),
    ...(t.modifiers ?? []),
  ].filter(Boolean);
  return parts.length ? parts.join(' · ') : 'All orders';
};


// ═══════════════════════════════════════════════════════════════════
// 6. Investigation errors — InvestigationView.error.code → what the analyst sees
// ═══════════════════════════════════════════════════════════════════
// ui-workflow.md v0.3 "Error messages". error.message is for developers and
// only shows under "Details". Every code allows Start again.
// Also used for CaseSummary.last_error, which holds the same code.
export const INVESTIGATION_ERROR_MESSAGES = {
  UPSTREAM_UNAVAILABLE: "A service didn't respond. Try again in a minute.",
  UNAUTHENTICATED: 'Your session expired during the run. Try again.',
  DOMAIN_REJECTED: 'The data service refused a request. Try again, and report it if it repeats.',
  MODEL_REFUSED: 'The AI model stopped before it could finish. Try again.',
  MODEL_TRUNCATED: "The AI model's answer was cut off. Try again.",
  RUN_TIMEOUT: 'The investigation ran over its time limit and stopped.',
  AGENT_RESTARTED: 'The agent service restarted during the run.',
  INTERNAL: 'Something went wrong. Try again, and report the investigation ID if it repeats.',
};

// Unknown or missing code → the INTERNAL message
export const formatInvestigationError = (code) =>
  INVESTIGATION_ERROR_MESSAGES[code] ?? INVESTIGATION_ERROR_MESSAGES.INTERNAL;


// ═══════════════════════════════════════════════════════════════════
// 7. Audit log — AuditEntry.action → a readable line
// ═══════════════════════════════════════════════════════════════════
// The values Domain writes (C-03, C-05): fixed actions, plus investigation.<status>
// from the agent's status reports and recheck.<status> when a recheck runs.
// investigation.started is written only by the mock.
export const AUDIT_ACTION_LABELS = {
  'case.opened': 'Case opened',
  // Domain writes investigation.<status> when the agent reports one (C-03);
  // the start arrives as investigation.running. investigation.started is the mock's.
  'investigation.running': 'Investigation started',
  'investigation.started': 'Investigation started',
  'investigation.awaiting_approval': 'Question waiting for approval',
  'investigation.awaiting_merchant': 'Waiting for the merchant',
  'investigation.completed': 'Investigation completed',
  'investigation.unsure': 'Investigation unsure',
  'investigation.failed': 'Investigation failed',
  'proposal.created': 'Proposal created',
  'proposal.edited': 'Proposal edited',
  'proposal.approved': 'Proposal approved',
  'proposal.rejected': 'Proposal rejected',
  'dispatch.sent': 'Sent',
  'dispatch.failed': 'Send failed',
  'merchant_reply.recorded': 'Merchant reply recorded',
  'recheck.scheduled': 'Recheck scheduled',
  'recheck.improved': 'Recheck: improved',
  'recheck.not_improved': 'Recheck: not improved',
  'recheck.insufficient_data': 'Recheck: not enough data',
};

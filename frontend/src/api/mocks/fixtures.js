// [06a] Investigation fixtures — contract-matched mock data (D-04)
//
// Shapes follow docs/contracts.md exactly:
//   InvestigationView · Hypothesis · CheckSummary · InvestigationResult
//   Proposal · MerchantReply
// Story lines follow docs/agent-graph.md:
//   CASE-0001 · STORE-A → POS modifier mapping, no merchant question
//   CASE-0002 · STORE-B → dinner packing, one merchant question
// IDs and numbers are illustrative. Real evidence IDs come from the C-01 seed.
//
// Two ways to use this file:
//   1. Named fixtures (section 6) → render one screen per status
//   2. buildView / buildResult / build*Proposal → used by mockInvestigations.js


// ═══════════════════════════════════════════════════════════════════
// 1. Helpers
// ═══════════════════════════════════════════════════════════════════
const clone = (value) => structuredClone(value);

// Check timestamps: one check every 30 s after the start
const addSeconds = (iso, seconds) => new Date(Date.parse(iso) + seconds * 1000).toISOString();

const NO_TARGET = { item_id: [], modifiers: [], daypart: [], item_count_min: null };


// ═══════════════════════════════════════════════════════════════════
// 2. STORE-A — POS modifier mapping (CASE-0001)
// ═══════════════════════════════════════════════════════════════════
const A = {
  POS: 'HYP-01JD3K9Y0001',
  MENU: 'HYP-01JD3K9Y0002',
  INV: 'HYP-01JD3K9Y0003',
  DOWN: 'HYP-01JD3K9Y0004',
};

const POS_SCENARIO = {
  case_id: 'CASE-0001',
  store_id: 'STORE-A',
  hypotheses: [
    { hypothesis_id: A.POS, cause_category: 'pos_modifier_mapping', statement: 'The Extra sauce modifier added on Oct 30 is mis-mapped on kitchen tickets.' },
    { hypothesis_id: A.MENU, cause_category: 'menu_change', statement: 'The Oct 30 drink rename confuses orders.' },
    { hypothesis_id: A.INV, cause_category: 'inventory', statement: 'Out-of-stock items are left out or substituted.' },
    { hypothesis_id: A.DOWN, cause_category: 'other', statement: 'The Oct 20 store downtime left a lasting backlog of errors.' },
  ],
  // Each check carries the hypothesis updates `reason` made after reading it
  checks: [
    {
      summary: {
        check_id: 'CHK-01JD3K9X',
        kind: 'explore',
        tool: 'store_overview',
        purpose: "Get the store's rate, claim mix and daily trend for the window.",
        discriminates: [],
        expectations: [],
        challenges: null,
        matched: {},
        headline: 'M&I rate rose from 1.6% to 6.8% after Oct 30, mostly incorrect_item and ingredient_error.',
        data_sufficient: true,
        evidence_ids: [],
      },
      updates: [],
    },
    {
      summary: {
        check_id: 'CHK-01JD3KA0',
        kind: 'explore',
        tool: 'event_log',
        purpose: 'List menu, POS, downtime and promotion events in the window.',
        discriminates: [],
        expectations: [],
        challenges: null,
        matched: {},
        headline: 'Oct 20 store_downtime. Oct 30 menu_change: Extra sauce modifier added, one drink renamed.',
        data_sufficient: true,
        evidence_ids: ['EV-EVT-000024', 'EV-EVT-000031'],
      },
      updates: [],
    },
    {
      summary: {
        check_id: 'CHK-01JD3KA1',
        kind: 'test',
        tool: 'claim_breakdown',
        purpose: 'Check whether claims concentrate on one modifier after Oct 30.',
        discriminates: [A.POS, A.MENU],
        expectations: [
          { hypothesis_id: A.POS, if_true: 'Extra sauce orders claim at 3x or more the store rate', if_false: 'No modifier stands out' },
          { hypothesis_id: A.MENU, if_true: 'The renamed drink shows a claim rise', if_false: 'The renamed drink stays at the store rate' },
        ],
        challenges: null,
        matched: { [A.POS]: 'if_true', [A.MENU]: 'if_false' },
        headline: 'Extra sauce orders: 21.0% claim rate (38 / 181). All other orders: 1.7%.',
        data_sufficient: true,
        evidence_ids: ['EV-CLM-004410', 'EV-CLM-004417'],
      },
      updates: [
        { hypothesis_id: A.POS, status: 'supported', rationale: 'Claims concentrate on Extra sauce orders after Oct 30.', add_supporting: ['EV-EVT-000031', 'EV-CLM-004410', 'EV-CLM-004417'] },
        { hypothesis_id: A.MENU, status: 'ruled_out', rationale: 'The renamed drink shows no claim rise.' },
      ],
    },
    {
      summary: {
        check_id: 'CHK-01JD3KA2',
        kind: 'test',
        tool: 'cancellation_breakdown',
        purpose: 'Check whether out-of-stock cancellations or the downtime overlap the claim rise.',
        discriminates: [A.INV, A.DOWN],
        expectations: [
          { hypothesis_id: A.INV, if_true: 'item_out_of_stock cancellations continue after Oct 30', if_false: 'They end before the rise' },
          { hypothesis_id: A.DOWN, if_true: 'Problems persist from Oct 20 onward', if_false: 'Downtime effects end before Oct 30' },
        ],
        challenges: null,
        matched: { [A.INV]: 'if_false', [A.DOWN]: 'if_false' },
        headline: 'item_out_of_stock cancellations ran Oct 24–26 only. Nothing unusual after Oct 30.',
        data_sufficient: true,
        evidence_ids: ['EV-CXL-000045'],
      },
      updates: [
        { hypothesis_id: A.INV, status: 'ruled_out', rationale: 'Out-of-stock cancellations ended before the claim rise.', add_contradicting: ['EV-CXL-000045'] },
        { hypothesis_id: A.DOWN, status: 'ruled_out', rationale: 'The Oct 20 downtime ended before the claim rise.', add_contradicting: ['EV-EVT-000024'] },
      ],
    },
    {
      summary: {
        check_id: 'CHK-01JD3KA5',
        kind: 'challenge',
        tool: 'compare_periods',
        purpose: 'Try to disprove the modifier cause: did orders without Extra sauce rise too?',
        discriminates: [A.POS],
        expectations: [
          { hypothesis_id: A.POS, if_true: 'Only Extra sauce orders rise after Oct 30', if_false: 'Orders without the modifier rise as well' },
        ],
        challenges: A.POS,
        matched: { [A.POS]: 'if_true' },
        headline: 'Target (Extra sauce): 1.9% → 21.0%. Control (no Extra sauce): 1.6% → 1.7%.',
        data_sufficient: true,
        evidence_ids: [],
      },
      updates: [
        { hypothesis_id: A.POS, status: 'supported', rationale: 'Survived the challenge: orders without the modifier stayed flat.' },
      ],
    },
  ],
};

// The contracts.md example, with the other ruled-out causes filled in
const POS_RESULT = {
  outcome: 'diagnosis',
  cause_category: 'pos_modifier_mapping',
  cause_started_at: '2026-10-30',
  confidence: 'high',
  summary:
    "Since Oct 30, about 1 in 5 orders with the Extra sauce modifier got an incorrect_item or ingredient_error claim. Orders without it stayed near the store's normal rate.",
  supporting_evidence_ids: ['EV-EVT-000031', 'EV-CLM-004410', 'EV-CLM-004417'],
  contradicting_evidence_ids: [],
  ruled_out: [
    { cause_category: 'menu_change', reason: 'The drink renamed in the same Oct 30 change shows no claim rise.', evidence_ids: [], check_ids: ['CHK-01JD3KA1'] },
    { cause_category: 'inventory', reason: 'item_out_of_stock cancellations ran Oct 24-26 and ended before the claim rise.', evidence_ids: ['EV-CXL-000045'], check_ids: ['CHK-01JD3KA2'] },
    { cause_category: 'other', reason: 'The Oct 20 store downtime ended before the claim rise.', evidence_ids: ['EV-EVT-000024'], check_ids: ['CHK-01JD3KA2'] },
  ],
  evidence_gaps: [],
  checks_tried: ['CHK-01JD3K9X', 'CHK-01JD3KA0', 'CHK-01JD3KA1', 'CHK-01JD3KA2', 'CHK-01JD3KA5'],
  challenge_check_ids: ['CHK-01JD3KA5'],
  unverified_reply_claims: [],
  recommendation: {
    kind: 'handoff',
    action_id: 'fix_modifier_mapping',
    owner_team: 'pos_team',
    rationale: 'The claim rise starts with the Oct 30 menu_change and is limited to orders with Extra sauce.',
    target: { ...NO_TARGET, modifiers: ['Extra sauce'] },
    recheck_after_days: 14,
  },
  proposal_id: 'PROP-0001',
};


// ═══════════════════════════════════════════════════════════════════
// 3. STORE-B — dinner packing with distractors (CASE-0002)
// ═══════════════════════════════════════════════════════════════════
// Follows the 10-turn example in docs/agent-graph.md.
// Checks 1–7 run before the merchant question. Check 8 runs after a reply.
const B = {
  PACK: 'HYP-01JD4B300001',
  MENU: 'HYP-01JD4B300002',
  PROMO: 'HYP-01JD4B300003',
  DASH: 'HYP-01JD4B300004',
};

const PACKING_SCENARIO = {
  case_id: 'CASE-0002',
  store_id: 'STORE-B',
  questionAfter: 7,
  hypotheses: [
    { hypothesis_id: B.PACK, cause_category: 'packing', statement: 'Large dinner orders, 5+ items, leave the store incomplete.' },
    { hypothesis_id: B.MENU, cause_category: 'menu_change', statement: 'The Nov 1 dessert price change causes order errors.' },
    { hypothesis_id: B.PROMO, cause_category: 'other', statement: 'Promotion volume, Nov 3–9, overloads the kitchen.' },
    { hypothesis_id: B.DASH, cause_category: 'dasher_handoff', statement: 'Whole bags are lost between the store and the Dasher.' },
  ],
  checks: [
    {
      summary: {
        check_id: 'CHK-01JD4B3A0001',
        kind: 'explore',
        tool: 'store_overview',
        purpose: "Get the store's rate, claim mix and daily trend for the window.",
        discriminates: [],
        expectations: [],
        challenges: null,
        matched: {},
        headline: 'M&I rate rose from 1.5% to 5.9% from Nov 3, mostly missing_item. 4 fraud claims excluded.',
        data_sufficient: true,
        evidence_ids: [],
      },
      updates: [],
    },
    {
      summary: {
        check_id: 'CHK-01JD4B3A0002',
        kind: 'explore',
        tool: 'event_log',
        purpose: 'List menu, POS, downtime and promotion events in the window.',
        discriminates: [],
        expectations: [],
        challenges: null,
        matched: {},
        headline: 'Nov 1 menu_change: dessert price. Promotion Nov 3–9.',
        data_sufficient: true,
        evidence_ids: ['EV-EVT-000052', 'EV-EVT-000053'],
      },
      updates: [],
    },
    {
      summary: {
        check_id: 'CHK-01JD4B3A0003',
        kind: 'test',
        tool: 'claim_breakdown',
        purpose: 'Check whether claims concentrate on large orders since Nov 3.',
        discriminates: [B.PACK, B.MENU],
        expectations: [
          { hypothesis_id: B.PACK, if_true: '5+ item orders hold a far larger share of claims than of orders', if_false: 'Claim share matches order share across sizes' },
          { hypothesis_id: B.MENU, if_true: 'Claims concentrate on the repriced dessert', if_false: 'Dessert claims stay flat' },
        ],
        challenges: null,
        matched: { [B.PACK]: 'if_true', [B.MENU]: 'if_false' },
        headline: '5+ item orders: 48% of claims vs 14% of orders.',
        data_sufficient: true,
        evidence_ids: ['EV-CLM-006102', 'EV-CLM-006118'],
      },
      updates: [
        { hypothesis_id: B.PACK, status: 'supported', rationale: 'Claims concentrate on 5+ item orders since Nov 3.', add_supporting: ['EV-CLM-006102', 'EV-CLM-006118'] },
        { hypothesis_id: B.MENU, status: 'ruled_out', rationale: "A price change can't explain missing items on large orders." },
      ],
    },
    {
      summary: {
        check_id: 'CHK-01JD4B3A0004',
        kind: 'test',
        tool: 'claim_breakdown',
        purpose: 'Check which daypart the large-order claims sit in.',
        discriminates: [B.PACK, B.PROMO],
        expectations: [
          { hypothesis_id: B.PACK, if_true: 'Concentrated in one daypart', if_false: 'Spread across all dayparts' },
        ],
        challenges: null,
        matched: { [B.PACK]: 'if_true' },
        headline: 'Dinner 5+ item orders: 14.2% (29 / 204). Lunch 5+ item orders: 1.8% (3 / 167).',
        data_sufficient: true,
        evidence_ids: ['EV-CLM-006131'],
      },
      updates: [
        { hypothesis_id: B.PACK, status: 'supported', rationale: 'Narrowed to dinner orders with 5+ items.', add_supporting: ['EV-CLM-006131'] },
      ],
    },
    {
      summary: {
        check_id: 'CHK-01JD4B3A0005',
        kind: 'challenge',
        tool: 'compare_periods',
        purpose: 'Try to disprove packing: does the rate fall once the promotion ends on Nov 9?',
        discriminates: [B.PACK, B.PROMO],
        expectations: [
          { hypothesis_id: B.PACK, if_true: 'The rate stays high after Nov 10', if_false: 'The rate returns to normal after the promotion' },
          { hypothesis_id: B.PROMO, if_true: 'The rate falls after Nov 9', if_false: 'The rate stays high' },
        ],
        challenges: B.PACK,
        matched: { [B.PACK]: 'if_true', [B.PROMO]: 'if_false' },
        headline: 'Dinner 5+ items: 13.8% before Nov 10, 14.6% after. Control: 1.5% → 1.6%.',
        data_sufficient: true,
        evidence_ids: [],
      },
      updates: [
        { hypothesis_id: B.PACK, status: 'supported', rationale: 'Survived the challenge: the rate stayed high after the promotion.' },
        { hypothesis_id: B.PROMO, status: 'ruled_out', rationale: 'The rate stayed high after the promotion ended.' },
      ],
    },
    {
      summary: {
        check_id: 'CHK-01JD4B3A0006',
        kind: 'test',
        tool: 'cancellation_breakdown',
        purpose: 'Check whether busy-kitchen cancellations rose with the claims.',
        discriminates: [B.PROMO],
        expectations: [
          { hypothesis_id: B.PROMO, if_true: 'too_busy cancellations rise from Nov 3', if_false: 'too_busy cancellations are flat across the window' },
        ],
        challenges: null,
        matched: { [B.PROMO]: 'if_false' },
        headline: 'Friday dinner too_busy cancellations: same level before and after Nov 3.',
        data_sufficient: true,
        evidence_ids: ['EV-CXL-000210'],
      },
      updates: [
        { hypothesis_id: B.PROMO, status: 'ruled_out', rationale: 'Friday overload is long-standing and unrelated to the rise.', add_contradicting: ['EV-CXL-000210'] },
      ],
    },
    {
      summary: {
        check_id: 'CHK-01JD4B3A0007',
        kind: 'explore',
        tool: 'sample_evidence',
        purpose: 'Read customer comments on dinner claims for orders with 5+ items.',
        discriminates: [],
        expectations: [],
        challenges: null,
        matched: {},
        headline: '10 claims sampled. 6 mention a missing second bag.',
        data_sufficient: true,
        evidence_ids: ['EV-CLM-006140', 'EV-CLM-006155'],
      },
      updates: [
        { hypothesis_id: B.DASH, status: 'open', rationale: "Comments fit both store-side packing and a bag lost at handoff. Platform data can't separate them.", add_supporting: ['EV-CLM-006140'] },
      ],
    },
    // ── after the merchant reply ──
    {
      summary: {
        check_id: 'CHK-01JD4B3A0008',
        kind: 'test',
        tool: 'merchant_replies',
        purpose: "Read the merchant's answer about bagging large dinner orders.",
        discriminates: [B.PACK, B.DASH],
        expectations: [
          { hypothesis_id: B.PACK, if_true: 'The merchant describes a store-side bagging gap', if_false: 'The merchant confirms all bags are handed over together' },
        ],
        challenges: null,
        matched: { [B.PACK]: 'if_true' },
        headline: '1 reply: large dinner orders go out in two bags, and the second is sometimes left on the shelf.',
        data_sufficient: true,
        evidence_ids: ['EV-RPL-000001'],
      },
      updates: [
        { hypothesis_id: B.PACK, status: 'supported', rationale: 'The merchant reply matches the platform pattern.', add_supporting: ['EV-RPL-000001'] },
        { hypothesis_id: B.DASH, status: 'inconclusive', rationale: 'No Dasher data. The reply points to the store side.' },
      ],
    },
  ],
};

const PACKING_RULED_OUT = [
  { cause_category: 'menu_change', reason: 'The Nov 1 dessert price change cannot explain missing items on large orders.', evidence_ids: [], check_ids: ['CHK-01JD4B3A0003'] },
  { cause_category: 'other', reason: 'Promotion overload: the rate stayed high after the promotion ended, and too_busy cancellations did not rise.', evidence_ids: ['EV-CXL-000210'], check_ids: ['CHK-01JD4B3A0005', 'CHK-01JD4B3A0006'] },
];

const PACKING_RESULT = {
  outcome: 'diagnosis',
  cause_category: 'packing',
  cause_started_at: '2026-11-03',
  confidence: 'high',
  summary:
    'Since Nov 3, dinner orders with 5 or more items get missing_item claims at about 9x the store rate. The merchant says these orders now go out in two bags, and the second bag is sometimes left behind.',
  supporting_evidence_ids: ['EV-CLM-006102', 'EV-CLM-006118', 'EV-CLM-006131', 'EV-RPL-000001'],
  contradicting_evidence_ids: ['EV-CXL-000210'],
  ruled_out: PACKING_RULED_OUT,
  evidence_gaps: ["No Dasher data: dasher_handoff can't be tested from platform data."],
  checks_tried: PACKING_SCENARIO.checks.map((c) => c.summary.check_id),
  challenge_check_ids: ['CHK-01JD4B3A0005'],
  unverified_reply_claims: ['The second bag is sometimes left on the shelf during the dinner rush.'],
  recommendation: {
    kind: 'intervention',
    action_id: 'large_order_bag_check',
    owner_team: 'merchant',
    rationale: 'The rise is limited to dinner orders with 5+ items, and the merchant confirms a two-bag handover gap.',
    target: { ...NO_TARGET, daypart: ['dinner'], item_count_min: 5 },
    recheck_after_days: 14,
  },
  proposal_id: 'PROP-0003',
};

// Unsure: the question was rejected, or the merchant never replied.
// Without the answer, store-side packing and handoff can't be separated.
const PACKING_UNSURE_UPDATES = [
  { hypothesis_id: B.PACK, status: 'inconclusive', rationale: 'The pattern fits packing, but without the merchant answer it cannot be separated from handoff.' },
  { hypothesis_id: B.DASH, status: 'inconclusive', rationale: 'No Dasher data, and no merchant answer.' },
];

const packingUnsureResult = (reason) => ({
  outcome: 'unsure',
  cause_category: null,
  cause_started_at: '2026-11-03',
  confidence: 'low',
  summary:
    "Missing items rose on dinner orders with 5+ items from Nov 3, but platform data can't tell store-side packing from a bag lost at handoff.",
  supporting_evidence_ids: [],
  contradicting_evidence_ids: [],
  ruled_out: PACKING_RULED_OUT,
  evidence_gaps: [
    "No bag data: can't confirm how large orders are bagged.",
    "No Dasher data: dasher_handoff can't be tested from platform data.",
    reason === 'no_reply'
      ? 'The merchant did not reply to question PROP-0002.'
      : 'The merchant question PROP-0002 was rejected.',
  ],
  checks_tried: PACKING_SCENARIO.checks.slice(0, 7).map((c) => c.summary.check_id),
  challenge_check_ids: ['CHK-01JD4B3A0005'],
  unverified_reply_claims: [],
  recommendation: null,
  proposal_id: null,
});


// ═══════════════════════════════════════════════════════════════════
// 4. Builders — InvestigationView and InvestigationResult
// ═══════════════════════════════════════════════════════════════════
export const SCENARIOS = { pos: POS_SCENARIO, packing: PACKING_SCENARIO };

// Which scenario runs when a case starts an investigation
export const CASE_SCENARIOS = { 'CASE-0001': 'pos', 'CASE-0002': 'packing' };

// Replays the first `nChecks` checks' updates onto all-open hypotheses
const buildHypotheses = (scenario, nChecks, extraUpdates = []) => {
  const byId = new Map(
    scenario.hypotheses.map((h) => [
      h.hypothesis_id,
      {
        ...h,
        status: 'open',
        rationale: 'Not tested yet.',
        supporting_evidence_ids: [],
        contradicting_evidence_ids: [],
        check_ids: [],
      },
    ]),
  );

  const apply = (update, checkId) => {
    const h = byId.get(update.hypothesis_id);
    h.status = update.status;
    h.rationale = update.rationale;
    h.supporting_evidence_ids.push(...(update.add_supporting ?? []));
    h.contradicting_evidence_ids.push(...(update.add_contradicting ?? []));
    if (checkId && !h.check_ids.includes(checkId)) h.check_ids.push(checkId);
  };

  scenario.checks.slice(0, nChecks).forEach((c) => c.updates.forEach((u) => apply(u, c.summary.check_id)));
  extraUpdates.forEach((u) => apply(u, null));
  return [...byId.values()];
};

// outcome: 'diagnosis' | 'unsure_rejected' | 'unsure_no_reply'
export const buildResult = (scenarioName, outcome = 'diagnosis') => {
  if (scenarioName === 'pos') return clone(POS_RESULT);
  if (outcome === 'diagnosis') return clone(PACKING_RESULT);
  return packingUnsureResult(outcome === 'unsure_no_reply' ? 'no_reply' : 'rejected');
};

export const unsureUpdates = (scenarioName) => (scenarioName === 'packing' ? PACKING_UNSURE_UPDATES : []);

// Returns a fresh InvestigationView every call
export const buildView = ({
  scenario: scenarioName,
  investigation_id,
  status,
  nChecks,
  started_at,
  updated_at = null,
  started_by = 'USR-001',
  reopen_of = null,
  pending_proposal_id = null,
  result = null,
  error = null,
  extraUpdates = [],
  max_steps = 12,
}) => {
  const scenario = SCENARIOS[scenarioName];
  const checks = scenario.checks.slice(0, nChecks).map((c, i) => ({
    ...clone(c.summary),
    at: addSeconds(started_at, (i + 1) * 30),
  }));
  const lastAt = checks.length ? checks[checks.length - 1].at : started_at;

  return {
    investigation_id,
    case_id: scenario.case_id,
    store_id: scenario.store_id,
    status,
    started_by,
    started_at,
    updated_at: updated_at ?? lastAt,
    step_count: nChecks,
    max_steps,
    reopen_of,
    hypotheses: buildHypotheses(scenario, nChecks, extraUpdates),
    checks,
    pending_proposal_id,
    result: result ? clone(result) : null,
    error: error ? clone(error) : null,
  };
};


// ═══════════════════════════════════════════════════════════════════
// 5. Proposals and replies
// ═══════════════════════════════════════════════════════════════════
const pendingProposal = (fields) => ({
  version: 1,
  status: 'pending',
  decided_by: null,
  decided_at: null,
  decision_note: null,
  dispatch: null,
  ...fields,
});

export const buildQuestionProposal = ({ investigation_id, created_at }) =>
  pendingProposal({
    proposal_id: 'PROP-0002',
    case_id: 'CASE-0002',
    investigation_id,
    kind: 'merchant_question',
    content: {
      question_text:
        'How are dinner orders with 5 or more items bagged, and are all bags handed to the Dasher together?',
      why_asked: `Separates store-side packing (${B.PACK}) from Dasher handoff (${B.DASH}). Platform data has no bag or Dasher records.`,
    },
    evidence_ids: ['EV-CLM-006131', 'EV-CLM-006140'],
    created_at,
  });

const actionProposal = (proposal_id, case_id, investigation_id, created_at, result, title, instructions) => {
  const rec = result.recommendation;
  return pendingProposal({
    proposal_id,
    case_id,
    investigation_id,
    kind: rec.kind,
    content: {
      action_id: rec.action_id,
      owner_team: rec.owner_team,
      title,
      instructions,
      rationale: rec.rationale,
      target: clone(rec.target),
      recheck_after_days: rec.recheck_after_days,
    },
    evidence_ids: [...result.supporting_evidence_ids],
    created_at,
  });
};

export const buildRecommendationProposal = (scenarioName, { investigation_id, created_at }) =>
  scenarioName === 'pos'
    ? actionProposal(
        'PROP-0001', 'CASE-0001', investigation_id, created_at, POS_RESULT,
        'Fix the Extra sauce modifier mapping',
        'Check how the Extra sauce modifier added on Oct 30 maps to kitchen tickets, and correct the POS mapping.',
      )
    : actionProposal(
        'PROP-0003', 'CASE-0002', investigation_id, created_at, PACKING_RESULT,
        'Bag check for large dinner orders',
        'For dinner orders with 5+ items, count bags at packing and hand all bags to the Dasher together.',
      );


// ═══════════════════════════════════════════════════════════════════
// 6. Named fixtures — one per screen (static, never mutated)
// ═══════════════════════════════════════════════════════════════════
const POS_INV = 'INV-01JD3K9Q8F2M';
const POS_START = '2026-11-16T14:00:00Z';
const PACK_INV = 'INV-01JD4B2M7X9P';
const PACK_START = '2026-11-16T15:00:00Z';

export const investigationRunning = buildView({
  scenario: 'packing', investigation_id: PACK_INV, status: 'running', nChecks: 4, started_at: PACK_START,
});

export const investigationAwaitingApproval = buildView({
  scenario: 'packing', investigation_id: PACK_INV, status: 'awaiting_approval', nChecks: 7,
  started_at: PACK_START, pending_proposal_id: 'PROP-0002',
});

// Assumption: pending_proposal_id still points to the open question while
// awaiting_merchant, so the UI knows where to post the reply. Confirm with Member 2.
export const investigationAwaitingMerchant = buildView({
  scenario: 'packing', investigation_id: PACK_INV, status: 'awaiting_merchant', nChecks: 7,
  started_at: PACK_START, updated_at: '2026-11-16T15:10:00Z', pending_proposal_id: 'PROP-0002',
});

export const investigationCompleted = buildView({
  scenario: 'pos', investigation_id: POS_INV, status: 'completed', nChecks: 5,
  started_at: POS_START, result: POS_RESULT,
});

export const investigationPackingCompleted = buildView({
  scenario: 'packing', investigation_id: PACK_INV, status: 'completed', nChecks: 8,
  started_at: PACK_START, updated_at: '2026-11-17T16:05:00Z', result: PACKING_RESULT,
});

export const investigationUnsure = buildView({
  scenario: 'packing', investigation_id: PACK_INV, status: 'unsure', nChecks: 7,
  started_at: PACK_START, updated_at: '2026-11-16T15:12:00Z',
  result: packingUnsureResult('rejected'), extraUpdates: PACKING_UNSURE_UPDATES,
});

// An earlier run on CASE-0001 that failed after one check
export const investigationFailed = buildView({
  scenario: 'pos', investigation_id: 'INV-01JD3K7F0000', status: 'failed', nChecks: 1,
  started_at: '2026-11-16T13:40:00Z', updated_at: '2026-11-16T13:41:10Z',
  error: { code: 'UPSTREAM_UNAVAILABLE', message: 'The Domain Service did not respond after 2 retries.' },
});

export const proposalRecommendation = buildRecommendationProposal('pos', {
  investigation_id: POS_INV, created_at: '2026-11-16T14:03:00Z',
});

export const proposalQuestion = buildQuestionProposal({
  investigation_id: PACK_INV, created_at: '2026-11-16T15:04:00Z',
});

export const proposalPackingRecommendation = buildRecommendationProposal('packing', {
  investigation_id: PACK_INV, created_at: '2026-11-17T16:05:00Z',
});

export const merchantReply = {
  evidence_id: 'EV-RPL-000001',
  proposal_id: 'PROP-0002',
  outcome: 'replied',
  text: 'Since early November, large dinner orders go out in two bags. During the rush the second bag is sometimes left on the shelf.',
  recorded_by: 'USR-001',
  recorded_at: '2026-11-17T16:00:00Z',
};

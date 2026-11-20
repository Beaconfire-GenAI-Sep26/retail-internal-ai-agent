// [06a] Investigation fixtures — contract-matched mock data (D-04, ui-workflow v0.3)
//
// Shapes follow docs/contracts.md exactly:
//   InvestigationView · Hypothesis · CheckSummary · InvestigationResult
//   Proposal · MerchantReply · Recheck · RateWindow · Evidence · AuditEntry
// Story lines follow docs/agent-graph.md and the Case page map (ui-workflow.md):
//   CASE-0001 · STORE-A
//     1st run  pos            → POS modifier mapping, no merchant question → recheck improved
//     2nd run  pos_reopen     → unsure (only if a recheck is forced to fail)
//   CASE-0002 · STORE-B
//     1st run  packing        → dinner packing, one merchant question → recheck not improved
//     2nd run  packing_reopen → inventory (dinner sides run out) → recheck improved
// IDs and numbers are illustrative. Real evidence IDs come from the C-01 seed.
//
// Two ways to use this file:
//   1. Named fixtures (section 7) → render one screen per status
//   2. Builders (sections 4–6) → used by mockInvestigations.js


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
  proposal_id: null, // set by buildResult to the proposal Domain created
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
    action_id: 'add_large_order_bag_check', // agent catalog: tests/fixtures/domain/common/catalog.json
    owner_team: 'merchant',
    rationale: 'The rise is limited to dinner orders with 5+ items, and the merchant confirms a two-bag handover gap.',
    target: { ...NO_TARGET, daypart: ['dinner'], item_count_min: 5 },
    recheck_after_days: 14,
  },
  proposal_id: null,
};

// Unsure: the question was rejected, or the merchant never replied.
// Without the answer, store-side packing and handoff can't be separated.
const PACKING_UNSURE_UPDATES = [
  { hypothesis_id: B.PACK, status: 'inconclusive', rationale: 'The pattern fits packing, but without the merchant answer it cannot be separated from handoff.' },
  { hypothesis_id: B.DASH, status: 'inconclusive', rationale: 'No Dasher data, and no merchant answer.' },
];

// reason: 'rejected' | 'no_reply' · questionId: the merchant question's proposal_id
const packingUnsureResult = (reason, questionId) => ({
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
      ? `The merchant did not reply to question ${questionId}.`
      : `The merchant question ${questionId} was rejected.`,
  ],
  checks_tried: PACKING_SCENARIO.checks.slice(0, 7).map((c) => c.summary.check_id),
  challenge_check_ids: ['CHK-01JD4B3A0005'],
  unverified_reply_claims: [],
  recommendation: null,
  proposal_id: null,
});

Object.assign(PACKING_SCENARIO, {
  result: PACKING_RESULT,
  unsureResult: packingUnsureResult,
  unsureUpdates: PACKING_UNSURE_UPDATES,
  action: {
    title: 'Bag check for large dinner orders',
    instructions: 'For dinner orders with 5+ items, count bags at packing and hand all bags to the Dasher together.',
  },
});


// ═══════════════════════════════════════════════════════════════════
// 3b. Second runs — after a failed recheck reopens the case (step 8)
// ═══════════════════════════════════════════════════════════════════
// agent-graph.md "Reopening": the second run loads the first run's rulings,
// and the failed recheck counts against the cause that was acted on.
// `initial` is a hypothesis's state before the run's first check.

// ── STORE-B, 2nd run: the bag check failed → dinner sides run out ──
const B2 = {
  PACK: 'HYP-01JDR2B00001',
  INV: 'HYP-01JDR2B00002',
  DASH: 'HYP-01JDR2B00003',
  MENU: 'HYP-01JDR2B00004',
};

const PACKING_REOPEN_SCENARIO = {
  case_id: 'CASE-0002',
  store_id: 'STORE-B',
  hypotheses: [
    {
      hypothesis_id: B2.PACK, cause_category: 'packing',
      statement: 'Large dinner orders, 5+ items, leave the store incomplete.',
      initial: { status: 'open', rationale: 'Last fix failed: the bag check went out, but the recheck found no improvement (13.5%, 26 / 193).' },
    },
    { hypothesis_id: B2.INV, cause_category: 'inventory', statement: 'Dinner sides run out during the rush, so large orders go out short.' },
    { hypothesis_id: B2.DASH, cause_category: 'dasher_handoff', statement: 'Whole bags are lost between the store and the Dasher.' },
    {
      hypothesis_id: B2.MENU, cause_category: 'menu_change',
      statement: 'The Nov 1 dessert price change causes order errors.',
      initial: { status: 'ruled_out', rationale: 'Ruled out in the first investigation.' },
    },
  ],
  checks: [
    {
      summary: {
        check_id: 'CHK-01JDR2B0A001',
        kind: 'explore',
        tool: 'store_overview',
        purpose: "Get the store's rate and claim mix since the bag check went out.",
        discriminates: [],
        expectations: [],
        challenges: null,
        matched: {},
        headline: 'M&I rate stayed at 5.6% after the bag check, still mostly missing_item on dinner orders.',
        data_sufficient: true,
        evidence_ids: [],
      },
      updates: [],
    },
    {
      summary: {
        check_id: 'CHK-01JDR2B0A002',
        kind: 'test',
        tool: 'cancellation_breakdown',
        purpose: 'Check whether out-of-stock cancellations on dinner sides rose from Nov 3.',
        discriminates: [B2.INV],
        expectations: [
          { hypothesis_id: B2.INV, if_true: 'item_out_of_stock cancellations on sides rise from Nov 3', if_false: 'Out-of-stock cancellations stay flat' },
        ],
        challenges: null,
        matched: { [B2.INV]: 'if_true' },
        headline: 'Dinner item_out_of_stock cancellations: 0.4% before Nov 3, 3.1% after. Mostly Mac and Cheese and Coleslaw.',
        data_sufficient: true,
        evidence_ids: ['EV-CXL-000233', 'EV-CXL-000241'],
      },
      updates: [
        { hypothesis_id: B2.INV, status: 'supported', rationale: 'Sides run out at dinner from Nov 3, the same day claims rose.', add_supporting: ['EV-CXL-000233', 'EV-CXL-000241'] },
      ],
    },
    {
      summary: {
        check_id: 'CHK-01JDR2B0A003',
        kind: 'test',
        tool: 'claim_breakdown',
        purpose: 'Check which items the missing-item claims name on large dinner orders.',
        discriminates: [B2.INV, B2.PACK],
        expectations: [
          { hypothesis_id: B2.INV, if_true: 'Claims name the sides that run out', if_false: 'Claims are spread across all items' },
          { hypothesis_id: B2.PACK, if_true: 'Claims name whole bags, many items at once', if_false: 'Claims name single items' },
        ],
        challenges: null,
        matched: { [B2.INV]: 'if_true', [B2.PACK]: 'if_false' },
        headline: 'Sides make up 71% of missing items on large dinner orders (24 / 34). Most claims name one item.',
        data_sufficient: true,
        evidence_ids: ['EV-CLM-006188', 'EV-CLM-006203'],
      },
      updates: [
        { hypothesis_id: B2.INV, status: 'supported', rationale: 'Missing items are mostly the sides that run out.', add_supporting: ['EV-CLM-006188', 'EV-CLM-006203'] },
      ],
    },
    {
      summary: {
        check_id: 'CHK-01JDR2B0A004',
        kind: 'challenge',
        tool: 'compare_periods',
        purpose: 'Try to disprove inventory: did large dinner orders without these sides rise too?',
        discriminates: [B2.INV, B2.PACK],
        expectations: [
          { hypothesis_id: B2.INV, if_true: 'Only orders with the sides rise', if_false: 'Orders without the sides rise as well' },
          { hypothesis_id: B2.PACK, if_true: 'All large dinner orders rise', if_false: 'Large orders without the sides stay flat' },
        ],
        challenges: B2.INV,
        matched: { [B2.INV]: 'if_true', [B2.PACK]: 'if_false' },
        headline: 'Large dinner orders with the sides: 2.0% → 16.4%. Without them: 1.7% → 1.9%.',
        data_sufficient: true,
        evidence_ids: [],
      },
      updates: [
        { hypothesis_id: B2.INV, status: 'supported', rationale: 'Survived the challenge: orders without the sides stayed flat.' },
        { hypothesis_id: B2.PACK, status: 'ruled_out', rationale: 'Large orders without the sides stayed flat, and the bag check did not help.' },
      ],
    },
    {
      summary: {
        check_id: 'CHK-01JDR2B0A005',
        kind: 'explore',
        tool: 'sample_evidence',
        purpose: 'Read customer comments on dinner claims that name a side.',
        discriminates: [],
        expectations: [],
        challenges: null,
        matched: {},
        headline: '8 claims sampled. 6 say a side was missing. None mention a missing bag.',
        data_sufficient: true,
        evidence_ids: ['EV-CLM-006188', 'EV-CLM-006212'],
      },
      updates: [
        { hypothesis_id: B2.DASH, status: 'inconclusive', rationale: 'No Dasher data. The comments point to single items, not whole bags.', add_contradicting: ['EV-CLM-006212'] },
      ],
    },
  ],
};

PACKING_REOPEN_SCENARIO.result = {
  outcome: 'diagnosis',
  cause_category: 'inventory',
  cause_started_at: '2026-11-03',
  confidence: 'medium',
  summary:
    'Dinner sides, mostly Mac and Cheese and Coleslaw, run out by about 8 pm, so large orders go out short. Large dinner orders without these sides stayed near the store rate, and the bag check did not lower the rate.',
  supporting_evidence_ids: ['EV-CXL-000233', 'EV-CXL-000241', 'EV-CLM-006188', 'EV-CLM-006203'],
  contradicting_evidence_ids: [],
  ruled_out: [
    { cause_category: 'packing', reason: 'The bag check did not lower the rate, and large orders without the sides stayed flat.', evidence_ids: [], check_ids: ['CHK-01JDR2B0A004'] },
    PACKING_RULED_OUT[0],
  ],
  evidence_gaps: [
    "No stock-level data: run-outs are inferred from out-of-stock cancellations.",
    "No Dasher data: dasher_handoff can't be tested from platform data.",
  ],
  checks_tried: PACKING_REOPEN_SCENARIO.checks.map((c) => c.summary.check_id),
  challenge_check_ids: ['CHK-01JDR2B0A004'],
  unverified_reply_claims: [],
  recommendation: {
    kind: 'intervention',
    action_id: 'update_item_availability',
    owner_team: 'merchant',
    rationale: 'Missing items are the dinner sides that run out, and only orders with those sides rose.',
    target: { ...NO_TARGET, item_id: ['ITEM-B-007', 'ITEM-B-008'], daypart: ['dinner'] },
    recheck_after_days: 14,
  },
  proposal_id: null,
};
PACKING_REOPEN_SCENARIO.action = {
  title: 'Restock check for dinner sides',
  instructions: 'Before 5 pm, check Mac and Cheese and Coleslaw stock against the dinner forecast. Mark a side unavailable in the app as soon as it runs out.',
};

// ── STORE-A, 2nd run: the mapping fix "failed" → unsure ──
// Only reached when a CASE-0001 recheck is forced to fail: __mocks.nextRecheck('not_improved')
const A2 = {
  POS: 'HYP-01JDR2A00001',
  FRAUD: 'HYP-01JDR2A00002',
  MENU: 'HYP-01JDR2A00003',
};

const POS_REOPEN_SCENARIO = {
  case_id: 'CASE-0001',
  store_id: 'STORE-A',
  hypotheses: [
    {
      hypothesis_id: A2.POS, cause_category: 'pos_modifier_mapping',
      statement: 'The Extra sauce modifier is still mis-mapped on kitchen tickets.',
      initial: { status: 'open', rationale: 'Last fix failed: the mapping fix went out, but the recheck found no improvement.' },
    },
    { hypothesis_id: A2.FRAUD, cause_category: 'fraud_cluster', statement: 'A few customers file most of the Extra sauce claims.' },
    {
      hypothesis_id: A2.MENU, cause_category: 'menu_change',
      statement: 'The Oct 30 drink rename confuses orders.',
      initial: { status: 'ruled_out', rationale: 'Ruled out in the first investigation.' },
    },
  ],
  checks: [
    {
      summary: {
        check_id: 'CHK-01JDR2A0A001',
        kind: 'explore',
        tool: 'store_overview',
        purpose: "Get the store's rate and claim mix since the mapping fix.",
        discriminates: [],
        expectations: [],
        challenges: null,
        matched: {},
        headline: 'M&I rate stayed at 6.5% after the fix, still mostly ingredient_error.',
        data_sufficient: true,
        evidence_ids: [],
      },
      updates: [],
    },
    {
      summary: {
        check_id: 'CHK-01JDR2A0A002',
        kind: 'test',
        tool: 'claim_breakdown',
        purpose: 'Check whether claims still concentrate on Extra sauce orders after the fix.',
        discriminates: [A2.POS],
        expectations: [
          { hypothesis_id: A2.POS, if_true: 'Extra sauce orders still claim far above the store rate', if_false: 'Extra sauce orders return to the store rate' },
        ],
        challenges: null,
        matched: { [A2.POS]: 'if_true' },
        headline: 'Extra sauce orders: 20.6% (35 / 170). Claims still name the sauce as missing.',
        data_sufficient: true,
        evidence_ids: ['EV-CLM-004502', 'EV-CLM-004511'],
      },
      updates: [
        { hypothesis_id: A2.POS, status: 'inconclusive', rationale: "The pattern persists after the fix. Platform data can't tell whether the fix reached the kitchen printer.", add_supporting: ['EV-CLM-004502', 'EV-CLM-004511'] },
      ],
    },
    {
      summary: {
        check_id: 'CHK-01JDR2A0A003',
        kind: 'test',
        tool: 'fraud_signals',
        purpose: 'Check whether a few customers file most of the Extra sauce claims.',
        discriminates: [A2.FRAUD],
        expectations: [
          { hypothesis_id: A2.FRAUD, if_true: 'A small group of customer_refs files most claims', if_false: 'Claims are spread across customers' },
        ],
        challenges: null,
        matched: { [A2.FRAUD]: 'if_false' },
        headline: 'No customer filed more than 2 claims. No cluster flagged.',
        data_sufficient: true,
        evidence_ids: [],
      },
      updates: [
        { hypothesis_id: A2.FRAUD, status: 'ruled_out', rationale: 'Claims are spread across customers.' },
      ],
    },
  ],
  result: null, // this run always ends unsure
  unsureResult: () => ({
    outcome: 'unsure',
    cause_category: null,
    cause_started_at: '2026-10-30',
    confidence: 'low',
    summary:
      "Extra sauce orders still claim at about 20% after the mapping fix. Platform data can't tell whether the fix never reached the kitchen printer or a different problem hits the same orders.",
    supporting_evidence_ids: [],
    contradicting_evidence_ids: [],
    ruled_out: [
      { cause_category: 'fraud_cluster', reason: 'Claims are spread across customers.', evidence_ids: [], check_ids: ['CHK-01JDR2A0A003'] },
      POS_RESULT.ruled_out[0],
    ],
    evidence_gaps: [
      "No kitchen ticket data: can't confirm the mapping fix reached the printer.",
    ],
    checks_tried: POS_REOPEN_SCENARIO.checks.map((c) => c.summary.check_id),
    challenge_check_ids: [],
    unverified_reply_claims: [],
    recommendation: null,
    proposal_id: null,
  }),
};

Object.assign(POS_SCENARIO, {
  result: POS_RESULT,
  action: {
    title: 'Fix the Extra sauce modifier mapping',
    instructions: 'Check how the Extra sauce modifier added on Oct 30 maps to kitchen tickets, and correct the POS mapping.',
  },
});


// ═══════════════════════════════════════════════════════════════════
// 4. Builders — InvestigationView and InvestigationResult
// ═══════════════════════════════════════════════════════════════════
export const SCENARIOS = {
  pos: POS_SCENARIO,
  packing: PACKING_SCENARIO,
  pos_reopen: POS_REOPEN_SCENARIO,
  packing_reopen: PACKING_REOPEN_SCENARIO,
};

// Which scenario a store's first run plays, and which its second run (after a reopen) plays.
// Keyed by store, not case: real case IDs come from the monitor in the order it
// opens them, so CASE-0001 is not always STORE-A.
export const STORE_SCENARIOS = { 'STORE-A': 'pos', 'STORE-B': 'packing' };
export const STORE_REOPEN_SCENARIOS = { 'STORE-A': 'pos_reopen', 'STORE-B': 'packing_reopen' };

// The case IDs the seeded demo usually opens. Only a fallback for a case the
// mock hasn't seen from Domain yet (e.g. in unit tests).
export const CASE_SCENARIOS = { 'CASE-0001': 'pos', 'CASE-0002': 'packing' };

// What a run does once its checks are done: 'ask' | 'complete' | 'unsure'
export const scenarioEnding = (scenarioName) => {
  const s = SCENARIOS[scenarioName];
  if (s.questionAfter) return 'ask';
  return s.result ? 'complete' : 'unsure';
};

// How many checks run before the ending above
export const scenarioRunTo = (scenarioName) => {
  const s = SCENARIOS[scenarioName];
  return s.questionAfter ?? s.checks.length;
};

// Replays the first `nChecks` checks' updates onto the hypotheses' starting state
const buildHypotheses = (scenario, nChecks, extraUpdates = []) => {
  const byId = new Map(
    scenario.hypotheses.map(({ initial, ...h }) => [
      h.hypothesis_id,
      {
        ...h,
        status: initial?.status ?? 'open',
        rationale: initial?.rationale ?? 'Not tested yet.',
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

// outcome: 'diagnosis' | 'unsure_rejected' | 'unsure_no_reply' | 'unsure'
// proposal_id: the recommendation's proposal (diagnosis only)
// question_id: the merchant question's proposal (packing unsure only)
export const buildResult = (scenarioName, outcome = 'diagnosis', { proposal_id = null, question_id = null } = {}) => {
  const s = SCENARIOS[scenarioName];
  if (outcome === 'diagnosis' && s.result) return { ...clone(s.result), proposal_id };
  const reason = outcome === 'unsure_no_reply' ? 'no_reply' : 'rejected';
  return clone(s.unsureResult(reason, question_id));
};

export const unsureUpdates = (scenarioName) => SCENARIOS[scenarioName].unsureUpdates ?? [];

// Returns a fresh InvestigationView every call
export const buildView = ({
  scenario: scenarioName,
  case_id = null, // the real case ID; defaults to the scenario's demo ID
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
    case_id: case_id ?? scenario.case_id,
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

// error.message is for developers; the UI picks its text from error.code
// (ui-workflow.md "Error messages"). One example message per contract code.
export const INVESTIGATION_ERRORS = {
  UPSTREAM_UNAVAILABLE: 'The Domain Service did not respond after 2 retries.',
  UNAUTHENTICATED: 'Domain returned 401 UNAUTHENTICATED for the forwarded token.',
  DOMAIN_REJECTED: 'Domain returned 403 STORE_NOT_PERMITTED for GET /stores/{store_id}/overview.',
  MODEL_REFUSED: 'The model declined the turn, after the fallback model.',
  MODEL_TRUNCATED: 'A reason turn hit max_tokens twice.',
  RUN_TIMEOUT: 'The run passed AGENT_RUN_TIMEOUT_SECONDS (1200).',
  AGENT_RESTARTED: 'The Agent Service restarted while the run was active.',
  INTERNAL: 'Unhandled exception in node run_check.',
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

// Only the packing run asks a question
export const buildQuestionProposal = ({ proposal_id = 'PROP-0002', case_id = 'CASE-0002', investigation_id, created_at }) =>
  pendingProposal({
    proposal_id,
    case_id,
    investigation_id,
    kind: 'merchant_question',
    content: {
      question_text:
        'How are dinner orders with 5 or more items bagged, and are all bags handed to the Dasher together?',
      why_asked: 'Separates store-side packing from a bag lost at Dasher handoff. Platform data has no bag or Dasher records.',
    },
    evidence_ids: ['EV-CLM-006131', 'EV-CLM-006140'],
    created_at,
  });

// The action proposal Domain creates from a diagnosis' recommendation
export const buildRecommendationProposal = (scenarioName, { proposal_id, case_id = null, investigation_id, created_at }) => {
  const s = SCENARIOS[scenarioName];
  const rec = s.result.recommendation;
  return pendingProposal({
    proposal_id,
    case_id: case_id ?? s.case_id,
    investigation_id,
    kind: rec.kind,
    content: {
      action_id: rec.action_id,
      owner_team: rec.owner_team,
      title: s.action.title,
      instructions: s.action.instructions,
      rationale: rec.rationale,
      target: clone(rec.target),
      recheck_after_days: rec.recheck_after_days,
    },
    evidence_ids: [...s.result.supporting_evidence_ids],
    created_at,
  });
};

// The mock merchant's answer, which arrives in the system on resume — matches check 8 of the packing run
export const SAMPLE_REPLY_TEXT =
  'Since early November, large dinner orders go out in two bags. During the rush the second bag is sometimes left on the shelf.';


// ═══════════════════════════════════════════════════════════════════
// 6. Rechecks — did the fix work? (step 6 → closed / paused / step 7)
// ═══════════════════════════════════════════════════════════════════
// Rates follow contracts.md "Rate rules": a window under MIN_GROUP_ORDERS
// eligible orders has rate null ("Not enough data"), never 0.
const MIN_GROUP_ORDERS = 30;

const dateOnly = (iso) => iso.slice(0, 10);
const addDays = (iso, days) => new Date(Date.parse(iso) + days * 86400000).toISOString();

export const rateWindow = (start, end, claims, eligible_orders) => ({
  start,
  end,
  claims,
  eligible_orders,
  rate: eligible_orders < MIN_GROUP_ORDERS ? null : Math.round((claims / eligible_orders) * 10000) / 10000,
});

// Per scenario with an action: the target's before window, and the after
// and control numbers for each outcome. `default` is what a demo run returns
// unless __mocks.nextRecheck(...) picks another.
const RECHECK_DATA = {
  pos: {
    default: 'improved',
    before: ['2026-10-30', '2026-11-15', 38, 181],
    improved: { after: [4, 176], control: [21, 1255] },
    not_improved: { after: [35, 170], control: [21, 1255] },
    insufficient_data: { after: [1, 14], control: [9, 120] },
  },
  packing: {
    default: 'not_improved', // the Case page map: the bag check fails, the case reopens
    before: ['2026-11-03', '2026-11-15', 29, 204],
    improved: { after: [5, 198], control: [17, 1062] },
    not_improved: { after: [26, 193], control: [17, 1062] },
    insufficient_data: { after: [2, 21], control: [3, 88] },
  },
  packing_reopen: {
    default: 'improved',
    before: ['2026-11-17', '2026-11-30', 26, 193],
    improved: { after: [6, 201], control: [16, 1040] },
    not_improved: { after: [25, 188], control: [16, 1040] },
    insufficient_data: { after: [2, 19], control: [3, 92] },
  },
};

export const RECHECK_STATUSES = ['improved', 'not_improved', 'insufficient_data'];
export const defaultRecheckOutcome = (scenarioName) => RECHECK_DATA[scenarioName]?.default ?? 'improved';

// Scheduled when an action is approved: dispatched_at + recheck_after_days
export const buildScheduledRecheck = (scenarioName, { recheck_id, proposal, dispatched_at }) => {
  const [start, end, claims, orders] = RECHECK_DATA[scenarioName].before;
  return {
    recheck_id,
    case_id: proposal.case_id,
    proposal_id: proposal.proposal_id,
    scheduled_for: addDays(dispatched_at, proposal.content.recheck_after_days),
    status: 'scheduled',
    target: clone(proposal.content.target),
    before: rateWindow(start, end, claims, orders),
    after: null,
    control: null,
    data_sufficient: null,
    ran_at: null,
  };
};

// The after window runs from the dispatch to the scheduled date. The control
// is the store's other orders over the same window.
export const runScheduledRecheck = (recheck, scenarioName, status, { dispatched_at, ran_at }) => {
  const data = RECHECK_DATA[scenarioName][status];
  const start = dateOnly(dispatched_at);
  const end = dateOnly(recheck.scheduled_for);
  return {
    ...clone(recheck),
    status,
    after: rateWindow(start, end, ...data.after),
    control: rateWindow(start, end, ...data.control),
    data_sufficient: status !== 'insufficient_data',
    ran_at,
  };
};


// ═══════════════════════════════════════════════════════════════════
// 6b. Evidence — GET /evidence/{evidence_id}
// ═══════════════════════════════════════════════════════════════════
// One record for every evidence ID cited above. customer_comments and reply
// text are untrusted: the UI shows them as plain text.
const claim = (evidence_id, store_id, occurred_at, summary, a) => ({
  evidence_id,
  type: 'claim',
  store_id,
  occurred_at,
  summary,
  attributes: {
    item_id: null,
    modifier_detail: null,
    customer_comments: null,
    error_charge: 0,
    review_label: 'store_fault',
    reviewed_at: null,
    item_count: 1,
    reported_at: occurred_at,
    ...a,
  },
});

const cancellation = (evidence_id, store_id, occurred_at, summary, a) => ({
  evidence_id,
  type: 'cancellation',
  store_id,
  occurred_at,
  summary,
  attributes: { item_id: null, canceled_at: occurred_at, ...a },
});

const event = (evidence_id, store_id, occurred_at, summary, a) => ({
  evidence_id,
  type: 'operational_event',
  store_id,
  occurred_at,
  summary,
  attributes: { started_at: occurred_at, ended_at: null, ...a },
});

const EVIDENCE_LIST = [
  // ── STORE-A ──
  event('EV-EVT-000024', 'STORE-A', '2026-10-20T19:00:00Z', 'Store downtime, Oct 20, 2 hours.', {
    event_type: 'store_downtime', ended_at: '2026-10-20T21:05:00Z', description: 'Tablet offline during dinner; orders paused.',
  }),
  event('EV-EVT-000031', 'STORE-A', '2026-10-30T15:00:00Z', 'Menu change, Oct 30: Extra sauce modifier added, one drink renamed.', {
    event_type: 'menu_change', description: 'Added paid modifier "Extra sauce" to entrees. Renamed "Boba Tea" to "Bubble Milk Tea".',
  }),
  claim('EV-CLM-004410', 'STORE-A', '2026-11-04T01:12:00Z', 'Ingredient error on Orange Chicken with Extra sauce.', {
    order_id: 'ORD-004410', item_id: 'ITEM-A-001', item_name: 'Orange Chicken', error_category: 'ingredient_error',
    modifier_detail: 'Extra sauce', customer_comments: 'Paid for extra sauce, got none. Second time this week.',
    error_charge: 1.5, daypart: 'dinner', item_count: 3, customer_ref: 'CUST-7F21',
  }),
  claim('EV-CLM-004417', 'STORE-A', '2026-11-05T18:40:00Z', 'Incorrect item on Kung Pao Chicken with Extra sauce.', {
    order_id: 'ORD-004417', item_id: 'ITEM-A-002', item_name: 'Kung Pao Chicken', error_category: 'incorrect_item',
    modifier_detail: 'Extra sauce', customer_comments: 'Sauce was on the side and it was the wrong one.',
    error_charge: 13.95, daypart: 'lunch', item_count: 2, customer_ref: 'CUST-0B9A',
  }),
  cancellation('EV-CXL-000045', 'STORE-A', '2026-10-25T00:30:00Z', 'Canceled: item out of stock (Egg Rolls), Oct 24.', {
    order_id: 'ORD-003012', item_id: 'ITEM-A-008', cancellation_category: 'item_out_of_stock', daypart: 'dinner',
  }),
  claim('EV-CLM-004502', 'STORE-A', '2026-11-20T00:55:00Z', 'Ingredient error on Beef and Broccoli with Extra sauce, after the fix.', {
    order_id: 'ORD-004502', item_id: 'ITEM-A-003', item_name: 'Beef and Broccoli', error_category: 'ingredient_error',
    modifier_detail: 'Extra sauce', customer_comments: 'No extra sauce again.', error_charge: 1.5, daypart: 'dinner',
    item_count: 2, customer_ref: 'CUST-44D0',
  }),
  claim('EV-CLM-004511', 'STORE-A', '2026-11-22T18:10:00Z', 'Ingredient error on Orange Chicken with Extra sauce, after the fix.', {
    order_id: 'ORD-004511', item_id: 'ITEM-A-001', item_name: 'Orange Chicken', error_category: 'ingredient_error',
    modifier_detail: 'Extra sauce', customer_comments: null, error_charge: 1.5, daypart: 'lunch',
    item_count: 1, customer_ref: 'CUST-9C3E',
  }),

  // ── STORE-B ──
  event('EV-EVT-000052', 'STORE-B', '2026-11-01T14:00:00Z', 'Menu change, Nov 1: dessert prices.', {
    event_type: 'menu_change', description: 'Pecan Pie Slice and Brownie repriced.',
  }),
  event('EV-EVT-000053', 'STORE-B', '2026-11-03T05:00:00Z', 'Promotion, Nov 3–9: 20% off family meals.', {
    event_type: 'promotion', ended_at: '2026-11-10T05:59:00Z', description: '20% off Family Meal for 4.',
  }),
  claim('EV-CLM-006102', 'STORE-B', '2026-11-04T01:30:00Z', 'Missing item on a 6-item dinner order (French Fries).', {
    order_id: 'ORD-006102', item_id: 'ITEM-B-006', item_name: 'French Fries', error_category: 'missing_item',
    customer_comments: 'Half the order was missing.', error_charge: 4.5, daypart: 'dinner', item_count: 6, customer_ref: 'CUST-21AA',
  }),
  claim('EV-CLM-006118', 'STORE-B', '2026-11-06T01:05:00Z', 'Missing item on a 7-item dinner order (Fried Chicken).', {
    order_id: 'ORD-006118', item_id: 'ITEM-B-003', item_name: 'Fried Chicken (3 pc)', error_category: 'missing_item',
    customer_comments: null, error_charge: 11.99, daypart: 'dinner', item_count: 7, customer_ref: 'CUST-5E10',
  }),
  claim('EV-CLM-006131', 'STORE-B', '2026-11-08T00:45:00Z', 'Missing item on a 5-item dinner order (Classic Cheeseburger).', {
    order_id: 'ORD-006131', item_id: 'ITEM-B-001', item_name: 'Classic Cheeseburger', error_category: 'missing_item',
    customer_comments: 'Only got one bag.', error_charge: 10.49, daypart: 'dinner', item_count: 5, customer_ref: 'CUST-8812',
  }),
  claim('EV-CLM-006140', 'STORE-B', '2026-11-09T01:20:00Z', 'Missing item on a 6-item dinner order (Family Meal for 4).', {
    order_id: 'ORD-006140', item_id: 'ITEM-B-005', item_name: 'Family Meal for 4', error_category: 'missing_item',
    customer_comments: 'The second bag never came. Driver said that was all.', error_charge: 39.99, daypart: 'dinner',
    item_count: 6, customer_ref: 'CUST-0F77',
  }),
  claim('EV-CLM-006155', 'STORE-B', '2026-11-11T00:15:00Z', 'Missing item on a 5-item dinner order (Onion Rings).', {
    order_id: 'ORD-006155', item_id: 'ITEM-B-009', item_name: 'Onion Rings', error_category: 'missing_item',
    customer_comments: 'Missing a whole bag with sides and drinks.', error_charge: 5.49, daypart: 'dinner',
    item_count: 5, customer_ref: 'CUST-A130',
  }),
  cancellation('EV-CXL-000210', 'STORE-B', '2026-10-24T00:40:00Z', 'Canceled: too busy, Friday dinner, Oct 23.', {
    order_id: 'ORD-005870', cancellation_category: 'too_busy', daypart: 'dinner',
  }),
  cancellation('EV-CXL-000233', 'STORE-B', '2026-11-05T01:50:00Z', 'Canceled: item out of stock (Mac and Cheese), Nov 4.', {
    order_id: 'ORD-006111', item_id: 'ITEM-B-007', cancellation_category: 'item_out_of_stock', daypart: 'dinner',
  }),
  cancellation('EV-CXL-000241', 'STORE-B', '2026-11-08T02:05:00Z', 'Canceled: item out of stock (Coleslaw), Nov 7.', {
    order_id: 'ORD-006135', item_id: 'ITEM-B-008', cancellation_category: 'item_out_of_stock', daypart: 'dinner',
  }),
  claim('EV-CLM-006188', 'STORE-B', '2026-11-19T01:40:00Z', 'Missing item on a 6-item dinner order (Mac and Cheese).', {
    order_id: 'ORD-006188', item_id: 'ITEM-B-007', item_name: 'Mac and Cheese', error_category: 'missing_item',
    customer_comments: 'No mac and cheese, everything else was there.', error_charge: 4.99, daypart: 'dinner',
    item_count: 6, customer_ref: 'CUST-3D42',
  }),
  claim('EV-CLM-006203', 'STORE-B', '2026-11-21T02:10:00Z', 'Missing item on a 5-item dinner order (Coleslaw).', {
    order_id: 'ORD-006203', item_id: 'ITEM-B-008', item_name: 'Coleslaw', error_category: 'missing_item',
    customer_comments: null, error_charge: 3.49, daypart: 'dinner', item_count: 5, customer_ref: 'CUST-77B1',
  }),
  claim('EV-CLM-006212', 'STORE-B', '2026-11-23T01:25:00Z', 'Missing item on a 7-item dinner order (Mac and Cheese).', {
    order_id: 'ORD-006212', item_id: 'ITEM-B-007', item_name: 'Mac and Cheese', error_category: 'missing_item',
    customer_comments: 'Two bags arrived, but the side was not in either. <b>Please fix</b>', error_charge: 4.99,
    daypart: 'dinner', item_count: 7, customer_ref: 'CUST-12EE',
  }),
];

export const EVIDENCE = Object.fromEntries(EVIDENCE_LIST.map((e) => [e.evidence_id, e]));

// A recorded MerchantReply as Evidence (type merchant_reply)
export const replyToEvidence = (reply, store_id) => ({
  evidence_id: reply.evidence_id,
  type: 'merchant_reply',
  store_id,
  occurred_at: reply.recorded_at,
  summary: reply.outcome === 'replied' ? 'Merchant reply to a question.' : 'The merchant did not reply.',
  attributes: {
    proposal_id: reply.proposal_id,
    outcome: reply.outcome,
    text: reply.text,
    recorded_at: reply.recorded_at,
  },
});


// ═══════════════════════════════════════════════════════════════════
// 7. Named fixtures — one per screen (static, never mutated)
// ═══════════════════════════════════════════════════════════════════
const POS_INV = 'INV-01JD3K9Q8F2M';
const POS_START = '2026-11-16T14:00:00Z';
const PACK_INV = 'INV-01JD4B2M7X9P';
const PACK_START = '2026-11-16T15:00:00Z';
const PACK2_INV = 'INV-01JDR2B5Q1KZ';
const PACK2_START = '2026-12-01T15:05:00Z';

// Step 2
export const investigationRunning = buildView({
  scenario: 'packing', investigation_id: PACK_INV, status: 'running', nChecks: 4, started_at: PACK_START,
});

// Step 3
export const investigationAwaitingApproval = buildView({
  scenario: 'packing', investigation_id: PACK_INV, status: 'awaiting_approval', nChecks: 7,
  started_at: PACK_START, pending_proposal_id: 'PROP-0002',
});

// Step 4. Assumption: pending_proposal_id still points to the open question while
// awaiting_merchant, so the UI knows where to post the reply. Confirm with Member 2.
export const investigationAwaitingMerchant = buildView({
  scenario: 'packing', investigation_id: PACK_INV, status: 'awaiting_merchant', nChecks: 7,
  started_at: PACK_START, updated_at: '2026-11-16T15:10:00Z', pending_proposal_id: 'PROP-0002',
});

// Step 5
export const investigationCompleted = buildView({
  scenario: 'pos', investigation_id: POS_INV, status: 'completed', nChecks: 5,
  started_at: POS_START, result: buildResult('pos', 'diagnosis', { proposal_id: 'PROP-0001' }),
});

export const investigationPackingCompleted = buildView({
  scenario: 'packing', investigation_id: PACK_INV, status: 'completed', nChecks: 8,
  started_at: PACK_START, updated_at: '2026-11-16T15:48:00Z',
  result: buildResult('packing', 'diagnosis', { proposal_id: 'PROP-0003' }),
});

// Unsure
export const investigationUnsure = buildView({
  scenario: 'packing', investigation_id: PACK_INV, status: 'unsure', nChecks: 7,
  started_at: PACK_START, updated_at: '2026-11-16T15:12:00Z',
  result: buildResult('packing', 'unsure_rejected', { question_id: 'PROP-0002' }),
  extraUpdates: PACKING_UNSURE_UPDATES,
});

// Failed: an earlier run on CASE-0001 that failed after one check
export const investigationFailed = buildView({
  scenario: 'pos', investigation_id: 'INV-01JD3K7F0000', status: 'failed', nChecks: 1,
  started_at: '2026-11-16T13:40:00Z', updated_at: '2026-11-16T13:41:10Z',
  error: { code: 'UPSTREAM_UNAVAILABLE', message: INVESTIGATION_ERRORS.UPSTREAM_UNAVAILABLE },
});

// Step 8: the second run after the bag check failed, mid-way and finished
export const investigationReopenRunning = buildView({
  scenario: 'packing_reopen', investigation_id: PACK2_INV, status: 'running', nChecks: 2,
  started_at: PACK2_START, reopen_of: PACK_INV,
});

export const investigationReopenCompleted = buildView({
  scenario: 'packing_reopen', investigation_id: PACK2_INV, status: 'completed', nChecks: 5,
  started_at: PACK2_START, reopen_of: PACK_INV,
  result: buildResult('packing_reopen', 'diagnosis', { proposal_id: 'PROP-0004' }),
});

// Proposals
export const proposalRecommendation = buildRecommendationProposal('pos', {
  proposal_id: 'PROP-0001', investigation_id: POS_INV, created_at: '2026-11-16T14:03:00Z',
});

export const proposalQuestion = buildQuestionProposal({
  proposal_id: 'PROP-0002', investigation_id: PACK_INV, created_at: '2026-11-16T15:08:00Z',
});

export const proposalPackingRecommendation = buildRecommendationProposal('packing', {
  proposal_id: 'PROP-0003', investigation_id: PACK_INV, created_at: '2026-11-16T15:48:00Z',
});

// Step 6: approved and sent
export const proposalPackingApproved = {
  ...proposalPackingRecommendation,
  status: 'approved',
  decided_by: 'USR-001',
  decided_at: '2026-11-16T15:52:00Z',
  decision_note: null,
  dispatch: {
    dispatch_id: 'DSP-000002',
    status: 'dispatched',
    channel: 'mock_merchant',
    owner_team: 'merchant',
    dispatched_at: '2026-11-16T15:52:00Z',
  },
};

export const proposalReopenRecommendation = buildRecommendationProposal('packing_reopen', {
  proposal_id: 'PROP-0004', investigation_id: PACK2_INV, created_at: '2026-12-01T15:08:00Z',
});

export const merchantReply = {
  evidence_id: 'EV-RPL-000001',
  proposal_id: 'PROP-0002',
  outcome: 'replied',
  text: SAMPLE_REPLY_TEXT,
  recorded_by: 'USR-001',
  recorded_at: '2026-11-16T15:40:00Z',
};

// Step 6 → 7: the bag check's recheck, scheduled and then not improved
export const recheckScheduled = buildScheduledRecheck('packing', {
  recheck_id: 'RCK-0001', proposal: proposalPackingApproved, dispatched_at: '2026-11-16T15:52:00Z',
});

export const recheckNotImproved = runScheduledRecheck(recheckScheduled, 'packing', 'not_improved', {
  dispatched_at: '2026-11-16T15:52:00Z', ran_at: '2026-12-01T09:00:00Z',
});

export const recheckImproved = runScheduledRecheck(recheckScheduled, 'packing', 'improved', {
  dispatched_at: '2026-11-16T15:52:00Z', ran_at: '2026-12-01T09:00:00Z',
});

export const recheckInsufficient = runScheduledRecheck(recheckScheduled, 'packing', 'insufficient_data', {
  dispatched_at: '2026-11-16T15:52:00Z', ran_at: '2026-12-01T09:00:00Z',
});

// AuditLog: CASE-0002 up to step 6, oldest first
const audit = (n, actor_id, actor_role, action, proposal_id, version, at) => ({
  audit_id: `AUD-${String(n).padStart(6, '0')}`,
  case_id: 'CASE-0002',
  actor_id,
  actor_role,
  action,
  proposal_id,
  version,
  request_id: `req-${String(n).padStart(4, '0')}`,
  at,
});

export const auditPackingDispatched = [
  audit(1, 'svc_monitor', 'service', 'case.opened', null, null, '2026-11-15T09:00:00Z'),
  audit(2, 'USR-001', 'loe_analyst', 'investigation.started', null, null, '2026-11-16T15:00:00Z'),
  audit(3, 'svc_agent', 'service', 'proposal.created', 'PROP-0002', 1, '2026-11-16T15:08:00Z'),
  audit(4, 'USR-001', 'loe_analyst', 'proposal.approved', 'PROP-0002', 1, '2026-11-16T15:10:00Z'),
  audit(5, 'USR-001', 'loe_analyst', 'dispatch.sent', 'PROP-0002', 1, '2026-11-16T15:10:00Z'),
  audit(6, 'USR-001', 'loe_analyst', 'merchant_reply.recorded', 'PROP-0002', null, '2026-11-16T15:40:00Z'),
  audit(7, 'svc_agent', 'service', 'investigation.completed', null, null, '2026-11-16T15:48:00Z'),
  audit(8, 'svc_agent', 'service', 'proposal.created', 'PROP-0003', 1, '2026-11-16T15:48:00Z'),
  audit(9, 'USR-001', 'loe_analyst', 'proposal.approved', 'PROP-0003', 1, '2026-11-16T15:52:00Z'),
  audit(10, 'USR-001', 'loe_analyst', 'dispatch.sent', 'PROP-0003', 1, '2026-11-16T15:52:00Z'),
  audit(11, 'USR-001', 'loe_analyst', 'recheck.scheduled', 'PROP-0003', null, '2026-11-16T15:52:00Z'),
];

// Sample Evidence records, one per type
export const evidenceClaim = EVIDENCE['EV-CLM-006131'];
export const evidenceCancellation = EVIDENCE['EV-CXL-000233'];
export const evidenceEvent = EVIDENCE['EV-EVT-000031'];
export const evidenceReply = replyToEvidence(merchantReply, 'STORE-B');

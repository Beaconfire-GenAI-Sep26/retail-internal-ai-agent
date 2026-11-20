// [06b] Mock Agent + Domain endpoints for the investigation flow (D-04)
// Used only when VITE_USE_MOCKS=true, until B-03 / C-03 are running.
//
// Mirrors docs/contracts.md:
//   POST /agent/investigations                    → mockStartInvestigation
//   GET  /agent/investigations/{id}               → mockGetInvestigation
//   GET  /agent/investigations?case_id=           → mockListInvestigations
//   POST /agent/investigations/{id}/resume        → mockResumeInvestigation
//   GET  /domain/proposals/{id}                   → mockGetProposal
//   POST /domain/proposals/{id}/versions          → mockEditProposal
//   POST /domain/proposals/{id}/decision          → mockDecideProposal
//   POST /domain/proposals/{id}/merchant-reply    → mockRecordReply
//   GET  /domain/cases/{id}/merchant-replies      → mockListMerchantReplies
//
// Every function resolves to the same body the real endpoint returns, and
// rejects with an axios-like error carrying the contract error envelope:
//   err.response = { status, data: { error: { code, message, details, request_id } } }
// so thunks can use getErrorMessage / getErrorCode (api/errors.js) unchanged.
//
// The second argument is the request context: { user, idempotencyKey }.
// `user` is the logged-in User from the auth slice; the mock checks role and
// store grants the way the backend will.
//
// Flows (see docs/ui-workflow.md):
//   CASE-0001 · running → completed (POS modifier)
//   CASE-0002 · running → awaiting_approval
//       approve + resume → awaiting_merchant
//           reply + resume    → running → completed (packing)
//           no_reply + resume → running → unsure
//       reject + resume  → running → unsure
//   Any case after failNextStart() · running → failed
// While running, each GET advances the investigation by one check (≈ 2 s poll).


// ═══════════════════════════════════════════════════════════════════
// 1. Imports
// ═══════════════════════════════════════════════════════════════════
import {
  CASE_SCENARIOS,
  SCENARIOS,
  buildView,
  buildResult,
  unsureUpdates,
  buildQuestionProposal,
  buildRecommendationProposal,
} from './fixtures';


// ═══════════════════════════════════════════════════════════════════
// 2. Helpers — delay, clone, errors, access checks
// ═══════════════════════════════════════════════════════════════════
const delay = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const clone = (value) => structuredClone(value);
const now = () => new Date().toISOString();
const pad = (n, width) => String(n).padStart(width, '0');

const mockError = (status, code, message, details = null) => {
  const err = new Error(message);
  err.response = {
    status,
    data: { error: { code, message, details, request_id: `mock-${Date.now()}` } },
  };
  return err;
};

// 'analyst' is the role name in mockAuth.js before the D-01 contract update;
// the contract value is 'loe_analyst'. Accept both until that lands.
const isAnalyst = (user) => user?.role === 'loe_analyst' || user?.role === 'analyst';

const requireUser = (user) => {
  if (!user) throw mockError(401, 'UNAUTHENTICATED', 'Token missing, malformed or expired.');
};

const requireAnalyst = (user) => {
  requireUser(user);
  if (!isAnalyst(user)) throw mockError(403, 'FORBIDDEN', 'Your role cannot perform this action.');
};

// Single-resource reads hide other stores behind 404 (contracts.md "Errors")
const canSeeStore = (user, storeId) => (user?.store_ids ?? []).includes(storeId);

const FINAL = ['completed', 'unsure', 'failed'];


// ═══════════════════════════════════════════════════════════════════
// 3. In-memory state — reset on page reload
// ═══════════════════════════════════════════════════════════════════
let db;

export const resetMocks = () => {
  db = {
    investigations: new Map(), // investigation_id → record (section 4)
    proposals: new Map(),      // proposal_id → Proposal
    replies: new Map(),        // proposal_id → MerchantReply
    idempotency: new Map(),    // "<endpoint>:<key>" → stored response
    seq: { inv: 0, dsp: 0, rpl: 0 },
    failNext: false,
  };
};
resetMocks();

// Next start fails after one check, to show the `failed` screen
export const failNextStart = () => {
  db.failNext = true;
};

// Same key → same stored response, and nothing runs twice
const withIdempotency = async (endpoint, key, run) => {
  if (!key) return run();
  const cacheKey = `${endpoint}:${key}`;
  if (db.idempotency.has(cacheKey)) return clone(db.idempotency.get(cacheKey));
  const response = await run();
  db.idempotency.set(cacheKey, clone(response));
  return response;
};


// ═══════════════════════════════════════════════════════════════════
// 4. Investigation record → InvestigationView
// ═══════════════════════════════════════════════════════════════════
// A record runs checks up to `runTo`, then does `then`:
//   'ask'      → draft the merchant question, status awaiting_approval
//   'complete' → write the result and the recommendation proposal
//   'unsure'   → write an unsure result
//   'fail'     → status failed
const toView = (rec) =>
  buildView({
    scenario: rec.scenario,
    investigation_id: rec.investigation_id,
    status: rec.status,
    nChecks: rec.nChecks,
    started_at: rec.started_at,
    updated_at: rec.updated_at,
    started_by: rec.started_by,
    reopen_of: rec.reopen_of,
    pending_proposal_id: rec.pending_proposal_id,
    result: rec.result,
    error: rec.error,
    extraUpdates: rec.extraUpdates,
  });

const finishRun = (rec) => {
  rec.updated_at = now();

  if (rec.then === 'ask') {
    const proposal = buildQuestionProposal({ investigation_id: rec.investigation_id, created_at: now() });
    db.proposals.set(proposal.proposal_id, proposal);
    rec.status = 'awaiting_approval';
    rec.pending_proposal_id = proposal.proposal_id;
    return;
  }

  if (rec.then === 'complete') {
    const proposal = buildRecommendationProposal(rec.scenario, {
      investigation_id: rec.investigation_id,
      created_at: now(),
    });
    db.proposals.set(proposal.proposal_id, proposal);
    rec.status = 'completed';
    rec.pending_proposal_id = null;
    rec.result = buildResult(rec.scenario, 'diagnosis');
    return;
  }

  if (rec.then === 'unsure') {
    rec.status = 'unsure';
    rec.pending_proposal_id = null;
    rec.result = buildResult(rec.scenario, rec.unsureReason);
    rec.extraUpdates = unsureUpdates(rec.scenario);
    return;
  }

  rec.status = 'failed';
  rec.error = { code: 'UPSTREAM_UNAVAILABLE', message: 'The Domain Service did not respond after 2 retries.' };
};

// One poll = one step while running
const advance = (rec) => {
  if (rec.status !== 'running') return;
  if (rec.nChecks < rec.runTo) {
    rec.nChecks += 1;
    rec.updated_at = now();
  } else {
    finishRun(rec);
  }
};

const findInvestigation = (id, user) => {
  const rec = db.investigations.get(id);
  if (!rec || !canSeeStore(user, SCENARIOS[rec.scenario].store_id)) {
    throw mockError(404, 'NOT_FOUND', `Investigation ${id} not found.`);
  }
  return rec;
};


// ═══════════════════════════════════════════════════════════════════
// 5. Agent endpoints — start · get · list · resume
// ═══════════════════════════════════════════════════════════════════
// POST /agent/investigations → 202 InvestigationView (status running)
export const mockStartInvestigation = async ({ case_id, reopen_of = null }, { user } = {}) => {
  await delay(300);
  requireAnalyst(user);

  const scenarioName = CASE_SCENARIOS[case_id];
  if (!scenarioName || !canSeeStore(user, SCENARIOS[scenarioName].store_id)) {
    throw mockError(404, 'CASE_NOT_FOUND', `Case ${case_id} not found.`);
  }

  const runs = [...db.investigations.values()].filter((r) => r.case_id === case_id);
  if (runs.some((r) => !FINAL.includes(r.status))) {
    throw mockError(409, 'INVESTIGATION_ACTIVE', 'The case already has a running or paused investigation.');
  }
  if (reopen_of && !runs.some((r) => r.investigation_id === reopen_of)) {
    throw mockError(409, 'REOPEN_NOT_ALLOWED', `Investigation ${reopen_of} cannot be reopened.`);
  }

  db.seq.inv += 1;
  const scenario = SCENARIOS[scenarioName];
  const fail = db.failNext;
  db.failNext = false;

  const rec = {
    investigation_id: `INV-01JDM0CK${pad(db.seq.inv, 4)}`,
    case_id,
    scenario: scenarioName,
    started_by: user.user_id ?? 'USR-001',
    started_at: now(),
    updated_at: null,
    reopen_of,
    status: 'running',
    nChecks: 0,
    runTo: fail ? 1 : scenario.questionAfter ?? scenario.checks.length,
    then: fail ? 'fail' : scenario.questionAfter ? 'ask' : 'complete',
    unsureReason: null,
    pending_proposal_id: null,
    result: null,
    error: null,
    extraUpdates: [],
  };
  db.investigations.set(rec.investigation_id, rec);
  return toView(rec);
};

// GET /agent/investigations/{id} → InvestigationView
export const mockGetInvestigation = async (investigationId, { user } = {}) => {
  await delay(150);
  requireUser(user);
  const rec = findInvestigation(investigationId, user);
  advance(rec);
  return toView(rec);
};

// GET /agent/investigations?case_id= → InvestigationView[], newest first
export const mockListInvestigations = async (caseId, { user } = {}) => {
  await delay(150);
  requireUser(user);
  return [...db.investigations.values()]
    .filter((r) => r.case_id === caseId && canSeeStore(user, SCENARIOS[r.scenario].store_id))
    .reverse()
    .map(toView);
};

// POST /agent/investigations/{id}/resume → 202 InvestigationView
// Empty body. Like the real agent, it re-reads Domain state and does nothing
// when nothing changed.
export const mockResumeInvestigation = async (investigationId, { user, idempotencyKey } = {}) => {
  await delay(300);
  requireAnalyst(user);

  return withIdempotency(`resume:${investigationId}`, idempotencyKey, async () => {
    const rec = findInvestigation(investigationId, user);
    if (FINAL.includes(rec.status)) {
      throw mockError(409, 'INVESTIGATION_FINISHED', `Investigation ${investigationId} has already finished.`);
    }

    const proposal = db.proposals.get(rec.pending_proposal_id);
    const reply = db.replies.get(rec.pending_proposal_id);

    if (rec.status === 'awaiting_approval' && proposal?.status === 'approved') {
      rec.status = 'awaiting_merchant';
      rec.updated_at = now();
    } else if (rec.status === 'awaiting_approval' && proposal?.status === 'rejected') {
      // Question rejected → continue without asking → unsure
      Object.assign(rec, { status: 'running', then: 'unsure', unsureReason: 'unsure_rejected', updated_at: now() });
    } else if (rec.status === 'awaiting_merchant' && reply?.outcome === 'replied') {
      // Reply becomes evidence → one more check → diagnosis
      Object.assign(rec, { status: 'running', runTo: rec.nChecks + 1, then: 'complete', updated_at: now() });
    } else if (rec.status === 'awaiting_merchant' && reply?.outcome === 'no_reply') {
      Object.assign(rec, { status: 'running', then: 'unsure', unsureReason: 'unsure_no_reply', updated_at: now() });
    }
    // else: nothing changed in Domain → return the current view

    return toView(rec);
  });
};


// ═══════════════════════════════════════════════════════════════════
// 6. Domain endpoints — proposals and merchant replies
// ═══════════════════════════════════════════════════════════════════
const caseStore = (caseId) => SCENARIOS[CASE_SCENARIOS[caseId]]?.store_id;

const findProposal = (id, user) => {
  const proposal = db.proposals.get(id);
  if (!proposal || !canSeeStore(user, caseStore(proposal.case_id))) {
    throw mockError(404, 'NOT_FOUND', `Proposal ${id} not found.`);
  }
  return proposal;
};

// GET /domain/proposals/{id} → Proposal
export const mockGetProposal = async (proposalId, { user } = {}) => {
  await delay(150);
  requireUser(user);
  return clone(findProposal(proposalId, user));
};

// POST /domain/proposals/{id}/versions { content } → 201 Proposal, next version
export const mockEditProposal = async (proposalId, { content }, { user } = {}) => {
  await delay(300);
  requireAnalyst(user);
  const proposal = findProposal(proposalId, user);
  if (proposal.status !== 'pending') {
    throw mockError(409, 'ALREADY_DECIDED', `Proposal ${proposalId} is already ${proposal.status}.`);
  }
  proposal.content = clone(content);
  proposal.version += 1;
  return clone(proposal);
};

// POST /domain/proposals/{id}/decision { version, decision, note } → Proposal
export const mockDecideProposal = async (proposalId, { version, decision, note = null }, { user, idempotencyKey } = {}) => {
  await delay(300);
  requireAnalyst(user);

  return withIdempotency(`decision:${proposalId}`, idempotencyKey, async () => {
    const proposal = findProposal(proposalId, user);
    const wanted = decision === 'approve' ? 'approved' : 'rejected';

    if (proposal.status !== 'pending') {
      // Same decision again → 200 with the existing proposal, no second dispatch
      if (proposal.status === wanted) return clone(proposal);
      throw mockError(409, 'ALREADY_DECIDED', `Proposal ${proposalId} is already ${proposal.status}.`);
    }
    if (version !== proposal.version) {
      throw mockError(
        409,
        'STALE_VERSION',
        `Proposal ${proposalId} is at version ${proposal.version}. Review the latest version before deciding.`,
        { current_version: proposal.version },
      );
    }

    Object.assign(proposal, {
      status: wanted,
      decided_by: user.user_id ?? 'USR-001',
      decided_at: now(),
      decision_note: note,
    });

    if (wanted === 'approved') {
      db.seq.dsp += 1;
      const isQuestion = proposal.kind === 'merchant_question';
      proposal.dispatch = {
        dispatch_id: `DSP-${pad(db.seq.dsp, 6)}`,
        status: 'dispatched',
        channel: isQuestion ? 'mock_merchant' : 'mock_team_queue',
        owner_team: isQuestion ? 'merchant' : proposal.content.owner_team,
        dispatched_at: now(),
      };
    }
    return clone(proposal);
  });
};

// POST /domain/proposals/{id}/merchant-reply { outcome, text } → 201 MerchantReply
// Does not resume the investigation — the UI calls resume next.
export const mockRecordReply = async (proposalId, { outcome, text = null }, { user, idempotencyKey } = {}) => {
  await delay(300);
  requireAnalyst(user);

  return withIdempotency(`reply:${proposalId}`, idempotencyKey, async () => {
    const proposal = findProposal(proposalId, user);
    if (proposal.kind !== 'merchant_question' || proposal.dispatch?.status !== 'dispatched') {
      throw mockError(409, 'NOT_DISPATCHED', `Proposal ${proposalId} has not been sent to the merchant.`);
    }
    if (db.replies.has(proposalId)) {
      throw mockError(409, 'REPLY_EXISTS', `A reply is already recorded for ${proposalId}.`);
    }
    if (outcome === 'replied' && !text?.trim()) {
      throw mockError(422, 'VALIDATION_ERROR', 'text: required when outcome is "replied".');
    }

    db.seq.rpl += 1;
    const reply = {
      evidence_id: `EV-RPL-${pad(db.seq.rpl, 6)}`,
      proposal_id: proposalId,
      outcome,
      text: outcome === 'replied' ? text.trim() : null,
      recorded_by: user.user_id ?? 'USR-001',
      recorded_at: now(),
    };
    db.replies.set(proposalId, reply);
    return clone(reply);
  });
};

// GET /domain/cases/{id}/merchant-replies → MerchantReply[]
export const mockListMerchantReplies = async (caseId, { user } = {}) => {
  await delay(150);
  requireUser(user);
  if (!canSeeStore(user, caseStore(caseId))) {
    throw mockError(404, 'CASE_NOT_FOUND', `Case ${caseId} not found.`);
  }
  const ids = [...db.proposals.values()].filter((p) => p.case_id === caseId).map((p) => p.proposal_id);
  return ids.filter((id) => db.replies.has(id)).map((id) => clone(db.replies.get(id)));
};

// For the D-02 CaseDetail mock: CaseDetail.proposals and investigation_ids
export const getMockCaseExtras = (caseId) => ({
  proposals: [...db.proposals.values()].filter((p) => p.case_id === caseId).map(clone),
  investigation_ids: [...db.investigations.values()]
    .filter((r) => r.case_id === caseId)
    .reverse()
    .map((r) => r.investigation_id),
});


// ═══════════════════════════════════════════════════════════════════
// 7. Dev console helper — window.__mocks
// ═══════════════════════════════════════════════════════════════════
// In the browser console during `npm run dev`:
//   __mocks.failNextStart()   next Start investigation ends in `failed`
//   __mocks.reset()           clear all mock investigations and proposals
//   __mocks.db()              inspect the current mock state
if (typeof window !== 'undefined' && import.meta.env?.DEV) {
  window.__mocks = { failNextStart, reset: resetMocks, db: () => db };
}

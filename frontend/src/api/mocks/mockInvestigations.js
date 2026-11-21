// [06b] Mock Agent + Domain endpoints for the whole case workflow (D-04, ui-workflow v0.3)
// Used only when VITE_USE_MOCKS=true, until B-03/B-04 and C-03/C-04 are running.
//
// Mirrors docs/contracts.md:
//   Agent
//     POST /agent/investigations                    → mockStartInvestigation
//     GET  /agent/investigations/{id}               → mockGetInvestigation
//     GET  /agent/investigations?case_id=           → mockListInvestigations
//     POST /agent/investigations/{id}/resume        → mockResumeInvestigation
//   Domain
//     GET  /domain/cases, /domain/cases/{id}        → real API, then applyMockCaseList / applyMockCase
//     GET  /domain/cases/{id}/audit                 → mockListAudit
//     GET  /domain/cases/{id}/merchant-replies      → mockListMerchantReplies
//     GET  /domain/cases/{id}/rechecks              → mockListRechecks
//     GET  /domain/evidence/{id}                    → mockGetEvidence
//     GET  /domain/proposals/{id}                   → mockGetProposal
//     POST /domain/proposals/{id}/versions          → mockEditProposal
//     POST /domain/proposals/{id}/decision          → mockDecideProposal
//     POST /domain/proposals/{id}/merchant-reply    → mockRecordReply
//     POST /domain/rechecks/{id}/run                → mockRunRecheck
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
// Cases come from the real Domain API (C-02). Until C-03/C-04 write case
// status, proposals and rechecks, applyMockCase lays the mock's case state over
// the real CaseDetail, following contracts.md "Status model".
//
// Flows (ui-workflow.md "Workflow at a glance"). The scenario is picked by the
// case's store (STORE-A → pos, STORE-B → packing), so it still fits when the
// monitor numbers the cases differently. CASE-0001 / CASE-0002 below are the usual IDs.
//   CASE-0001 · running → completed (POS) → approve → action_dispatched
//       run recheck → improved → closed
//   CASE-0002 · running → awaiting_approval
//       approve + resume → awaiting_merchant
//           resume (reply arrives in the system) → running → completed (packing) → approve → action_dispatched
//               run recheck → not improved → reopened
//               start with reopen_of → 2nd run (inventory) → approve → run recheck → improved → closed
//           no_reply + resume → running → unsure → analyst_review
//       reject + resume  → running → unsure → analyst_review
//   Reject the action → analyst_review
//   A second not-improved recheck → analyst_review
// While running, each GET advances the investigation by one check (≈ 2 s poll).
//
// State survives a page reload (sessionStorage) so a demo can be refreshed.
// Dev console, during `npm run dev`:
//   __mocks.failNextStart('RUN_TIMEOUT')   next Start ends in `failed` with that code
//   __mocks.failNextDispatch()             next approval returns 502 DISPATCH_FAILED
//   __mocks.nextRecheck('insufficient_data')  next recheck result: improved | not_improved | insufficient_data
//   __mocks.reset()                        clear everything
//   __mocks.db()                           inspect the current mock state
//
// Audit actions written here (to be confirmed with C-03):
//   case.opened · investigation.started · investigation.completed · investigation.unsure ·
//   investigation.failed · proposal.created · proposal.edited · proposal.approved ·
//   proposal.rejected · dispatch.sent · dispatch.failed · merchant_reply.recorded ·
//   recheck.scheduled · recheck.improved · recheck.not_improved · recheck.insufficient_data


// ═══════════════════════════════════════════════════════════════════
// 1. Imports
// ═══════════════════════════════════════════════════════════════════
import {
  CASE_SCENARIOS,
  STORE_SCENARIOS,
  STORE_REOPEN_SCENARIOS,
  SCENARIOS,
  INVESTIGATION_ERRORS,
  RECHECK_STATUSES,
  EVIDENCE,
  buildView,
  buildResult,
  unsureUpdates,
  scenarioEnding,
  scenarioRunTo,
  buildQuestionProposal,
  buildRecommendationProposal,
  buildScheduledRecheck,
  runScheduledRecheck,
  defaultRecheckOutcome,
  replyToEvidence,
  SAMPLE_REPLY_TEXT,
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

// A case's store comes from the real CaseSummary (applyMockCaseSummary records it).
// Before Domain has shown the case, fall back to the demo IDs (unit tests).
const caseStore = (caseId) =>
  db.caseStores.get(caseId) ?? SCENARIOS[CASE_SCENARIOS[caseId]]?.store_id;

// The scenario a case's run plays, picked by its store
const scenarioForCase = (caseId, isSecond) =>
  (isSecond ? STORE_REOPEN_SCENARIOS : STORE_SCENARIOS)[caseStore(caseId)];

const requireCase = (caseId, user) => {
  const storeId = caseStore(caseId);
  if (!storeId || !canSeeStore(user, storeId)) {
    throw mockError(404, 'CASE_NOT_FOUND', `Case ${caseId} not found.`);
  }
  if (!STORE_SCENARIOS[storeId]) {
    throw mockError(404, 'CASE_NOT_FOUND', `The mock has no scenario for ${storeId}. Only ${Object.keys(STORE_SCENARIOS).join(' and ')} are scripted.`);
  }
};

const FINAL = ['completed', 'unsure', 'failed'];


// ═══════════════════════════════════════════════════════════════════
// 3. In-memory state — saved to sessionStorage after every change
// ═══════════════════════════════════════════════════════════════════
const STORAGE_KEY = 'mock-workflow-db-v2';
const MAPS = ['investigations', 'proposals', 'replies', 'rechecks', 'cases', 'caseStores', 'idempotency'];

let db;

const emptyDb = () => ({
  investigations: new Map(), // investigation_id → run record (section 4)
  proposals: new Map(),      // proposal_id → Proposal
  replies: new Map(),        // proposal_id → MerchantReply
  rechecks: new Map(),       // recheck_id → Recheck
  cases: new Map(),          // case_id → { status, last_error, reopen_count, reopened_from, updated_at }
  caseStores: new Map(),     // case_id → store_id, learned from the real CaseSummary
  audit: [],                 // AuditEntry[], oldest first
  idempotency: new Map(),    // "<endpoint>:<key>" → stored response
  seq: { inv: 0, prop: 0, dsp: 0, rpl: 0, rck: 0, aud: 0 },
  failNext: null,            // error code for the next Start, or null
  failNextDispatch: false,
  nextRecheck: null,         // recheck status for the next run, or null = scenario default
});

// Storage can throw (private mode) — the mock then just won't survive a reload
const save = () => {
  try {
    const plain = { ...db };
    MAPS.forEach((k) => { plain[k] = [...db[k].entries()]; });
    sessionStorage.setItem(STORAGE_KEY, JSON.stringify(plain));
  } catch {
    // ignore
  }
};

const load = () => {
  try {
    const raw = sessionStorage.getItem(STORAGE_KEY);
    if (!raw) return null;
    const plain = JSON.parse(raw);
    const loaded = { ...emptyDb(), ...plain };
    MAPS.forEach((k) => { loaded[k] = new Map(plain[k] ?? []); });
    return loaded;
  } catch {
    return null;
  }
};

export const resetMocks = () => {
  db = emptyDb();
  try {
    sessionStorage.removeItem(STORAGE_KEY);
  } catch {
    // ignore
  }
};

db = (typeof sessionStorage !== 'undefined' && load()) || emptyDb();

// Next Start fails after one check, to show the `failed` screen.
// code: one of the contract's investigation error codes
export const failNextStart = (code = 'UPSTREAM_UNAVAILABLE') => {
  if (!INVESTIGATION_ERRORS[code]) throw new Error(`Unknown code. Use one of: ${Object.keys(INVESTIGATION_ERRORS).join(', ')}`);
  db.failNext = code;
  save();
};

// Next approval returns 502 DISPATCH_FAILED and the proposal stays pending
export const failNextDispatch = () => {
  db.failNextDispatch = true;
  save();
};

// Next recheck result, instead of the scenario's default
export const setNextRecheck = (status) => {
  if (!RECHECK_STATUSES.includes(status)) throw new Error(`Use one of: ${RECHECK_STATUSES.join(', ')}`);
  db.nextRecheck = status;
  save();
};

// Same key → same stored response, and nothing runs twice.
// A failed call is not stored, so a retry with the same key runs again.
const withIdempotency = async (endpoint, key, run) => {
  if (!key) return run();
  const cacheKey = `${endpoint}:${key}`;
  if (db.idempotency.has(cacheKey)) return clone(db.idempotency.get(cacheKey));
  const response = await run();
  db.idempotency.set(cacheKey, clone(response));
  return response;
};

const nextProposalId = () => `PROP-${pad(++db.seq.prop, 4)}`;


// ═══════════════════════════════════════════════════════════════════
// 4. Case state and audit — what Domain records (contracts.md "Status model")
// ═══════════════════════════════════════════════════════════════════
const caseState = (caseId) => {
  if (!db.cases.has(caseId)) {
    db.cases.set(caseId, { status: 'open', last_error: null, reopen_count: 0, reopened_from: null, updated_at: now() });
  }
  return db.cases.get(caseId);
};

const setCase = (caseId, patch) => Object.assign(caseState(caseId), patch, { updated_at: now() });

// actor: the logged-in User, or 'svc_agent' / 'svc_monitor'
const audit = (caseId, actor, action, { proposal_id = null, version = null } = {}) => {
  db.seq.aud += 1;
  const isService = typeof actor === 'string';
  db.audit.push({
    audit_id: `AUD-${pad(db.seq.aud, 6)}`,
    case_id: caseId,
    actor_id: isService ? actor : (actor.user_id ?? 'USR-001'),
    actor_role: isService ? 'service' : actor.role,
    action,
    proposal_id,
    version,
    request_id: `mock-req-${pad(db.seq.aud, 4)}`,
    at: now(),
  });
};

const runsOf = (caseId) => [...db.investigations.values()].filter((r) => r.case_id === caseId);


// ═══════════════════════════════════════════════════════════════════
// 5. Investigation record → InvestigationView
// ═══════════════════════════════════════════════════════════════════
// A record runs checks up to `runTo`, then does `then`:
//   'ask'      → draft the merchant question, status awaiting_approval
//   'complete' → write the result and the recommendation proposal
//   'unsure'   → write an unsure result
//   'fail'     → status failed
const toView = (rec) => {
  const view = buildView({
    scenario: rec.scenario,
    case_id: rec.case_id,
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
  // Fixtures cite the reply as EV-RPL-000001; use the ID Domain actually issued
  if (rec.reply_evidence_id && rec.reply_evidence_id !== 'EV-RPL-000001') {
    return JSON.parse(JSON.stringify(view).replaceAll('EV-RPL-000001', rec.reply_evidence_id));
  }
  return view;
};

const finishRun = (rec) => {
  rec.updated_at = now();

  if (rec.then === 'ask') {
    const proposal = buildQuestionProposal({
      proposal_id: nextProposalId(), case_id: rec.case_id, investigation_id: rec.investigation_id, created_at: now(),
    });
    db.proposals.set(proposal.proposal_id, proposal);
    rec.status = 'awaiting_approval';
    rec.pending_proposal_id = proposal.proposal_id;
    rec.question_id = proposal.proposal_id;
    setCase(rec.case_id, { status: 'awaiting_decision' });
    audit(rec.case_id, 'svc_agent', 'proposal.created', { proposal_id: proposal.proposal_id, version: 1 });
    return;
  }

  if (rec.then === 'complete') {
    const proposal = buildRecommendationProposal(rec.scenario, {
      proposal_id: nextProposalId(), case_id: rec.case_id, investigation_id: rec.investigation_id, created_at: now(),
    });
    db.proposals.set(proposal.proposal_id, proposal);
    rec.status = 'completed';
    rec.pending_proposal_id = null;
    rec.result = buildResult(rec.scenario, 'diagnosis', { proposal_id: proposal.proposal_id });
    setCase(rec.case_id, { status: 'awaiting_decision' });
    audit(rec.case_id, 'svc_agent', 'investigation.completed');
    audit(rec.case_id, 'svc_agent', 'proposal.created', { proposal_id: proposal.proposal_id, version: 1 });
    return;
  }

  if (rec.then === 'unsure') {
    rec.status = 'unsure';
    rec.pending_proposal_id = null;
    rec.result = buildResult(rec.scenario, rec.unsureReason ?? 'unsure', { question_id: rec.question_id });
    rec.extraUpdates = rec.unsureReason ? unsureUpdates(rec.scenario) : [];
    setCase(rec.case_id, { status: 'analyst_review' });
    audit(rec.case_id, 'svc_agent', 'investigation.unsure');
    return;
  }

  rec.status = 'failed';
  rec.error = { code: rec.failCode, message: INVESTIGATION_ERRORS[rec.failCode] };
  setCase(rec.case_id, { status: 'open', last_error: rec.failCode });
  audit(rec.case_id, 'svc_agent', 'investigation.failed');
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
// 6. Agent endpoints — start · get · list · resume
// ═══════════════════════════════════════════════════════════════════
// POST /agent/investigations { case_id, reopen_of } → 202 InvestigationView (status running)
export const mockStartInvestigation = async ({ case_id, reopen_of = null }, { user } = {}) => {
  await delay(300);
  requireAnalyst(user);
  requireCase(case_id, user);

  const runs = runsOf(case_id);
  const active = runs.find((r) => !FINAL.includes(r.status));
  if (active) {
    throw mockError(409, 'INVESTIGATION_ACTIVE', 'The case already has a running or paused investigation.', {
      investigation_id: active.investigation_id,
    });
  }

  const cs = caseState(case_id);
  if (reopen_of && (cs.status !== 'reopened' || !runs.some((r) => r.investigation_id === reopen_of))) {
    throw mockError(409, 'REOPEN_NOT_ALLOWED', `Case ${case_id} is not reopened, or ${reopen_of} is not its last run.`);
  }

  // After a reopen every later run (including "Start again" after a failed
  // second run) plays the second-run scenario and keeps pointing at the first run.
  const isSecond = Boolean(reopen_of) || cs.reopen_count > 0;
  const scenarioName = scenarioForCase(case_id, isSecond);
  const failCode = db.failNext;
  db.failNext = null;

  db.seq.inv += 1;
  const rec = {
    investigation_id: `INV-01JDM0CK${pad(db.seq.inv, 4)}`,
    case_id,
    scenario: scenarioName,
    started_by: user.user_id ?? 'USR-001',
    started_at: now(),
    updated_at: null,
    reopen_of: reopen_of ?? (isSecond ? cs.reopened_from : null),
    status: 'running',
    nChecks: 0,
    runTo: failCode ? 1 : scenarioRunTo(scenarioName),
    then: failCode ? 'fail' : scenarioEnding(scenarioName),
    failCode,
    unsureReason: null,
    question_id: null,
    reply_evidence_id: null,
    pending_proposal_id: null,
    result: null,
    error: null,
    extraUpdates: [],
  };
  db.investigations.set(rec.investigation_id, rec);
  setCase(case_id, { status: 'investigating', last_error: null });
  audit(case_id, user, 'investigation.started');
  save();
  return toView(rec);
};

// GET /agent/investigations/{id} → InvestigationView
export const mockGetInvestigation = async (investigationId, { user } = {}) => {
  await delay(150);
  requireUser(user);
  const rec = findInvestigation(investigationId, user);
  advance(rec);
  save();
  return toView(rec);
};

// GET /agent/investigations?case_id= → InvestigationView[], newest first
export const mockListInvestigations = async (caseId, { user } = {}) => {
  await delay(150);
  requireUser(user);
  return runsOf(caseId)
    .filter((r) => canSeeStore(user, SCENARIOS[r.scenario].store_id))
    .reverse()
    .map(toView);
};

// POST /agent/investigations/{id}/resume → 202 InvestigationView
// Empty body. Like the real agent, it re-reads Domain state and does nothing
// when nothing changed.
export const mockResumeInvestigation = async (investigationId, { user, idempotencyKey } = {}) => {
  await delay(300);
  requireAnalyst(user);

  const view = await withIdempotency(`resume:${investigationId}`, idempotencyKey, async () => {
    const rec = findInvestigation(investigationId, user);
    if (FINAL.includes(rec.status)) {
      throw mockError(409, 'INVESTIGATION_FINISHED', `Investigation ${investigationId} has already finished.`);
    }

    const proposal = db.proposals.get(rec.pending_proposal_id);
    // The merchant's answer reaches Domain on its own, not through the analyst.
    // The analyst confirms it arrived by resuming; the mock plays that arrival here.
    if (rec.status === 'awaiting_merchant' && proposal && !db.replies.has(proposal.proposal_id)) {
      saveReply(proposal, 'replied', SAMPLE_REPLY_TEXT, 'svc-merchant-inbox');
    }
    const reply = db.replies.get(rec.pending_proposal_id);
    const run = (patch) => {
      Object.assign(rec, { status: 'running', updated_at: now() }, patch);
      setCase(rec.case_id, { status: 'investigating' });
    };

    if (rec.status === 'awaiting_approval' && proposal?.status === 'approved') {
      // Domain already moved the case to awaiting_merchant when it dispatched
      rec.status = 'awaiting_merchant';
      rec.updated_at = now();
    } else if (rec.status === 'awaiting_approval' && proposal?.status === 'rejected') {
      // Question rejected → continue without asking → unsure
      run({ pending_proposal_id: null, then: 'unsure', unsureReason: 'unsure_rejected' });
    } else if (rec.status === 'awaiting_merchant' && reply?.outcome === 'replied') {
      // Reply becomes evidence → one more check → diagnosis
      run({ pending_proposal_id: null, runTo: rec.nChecks + 1, then: 'complete', reply_evidence_id: reply.evidence_id });
    } else if (rec.status === 'awaiting_merchant' && reply?.outcome === 'no_reply') {
      run({ pending_proposal_id: null, then: 'unsure', unsureReason: 'unsure_no_reply' });
    }
    // else: nothing changed in Domain → return the current view

    return toView(rec);
  });
  save();
  return view;
};


// ═══════════════════════════════════════════════════════════════════
// 7. Domain — case overlay, audit, replies, rechecks, evidence
// ═══════════════════════════════════════════════════════════════════
// Lays the mock case state over a real CaseSummary. Untouched cases pass through.
// Also records the case's store, which picks the scenario it plays.
export const applyMockCaseSummary = (summary) => {
  if (summary.store_id && db.caseStores.get(summary.case_id) !== summary.store_id) {
    db.caseStores.set(summary.case_id, summary.store_id);
    save();
  }
  const cs = db.cases.get(summary.case_id);
  if (!cs) return summary;
  const active = runsOf(summary.case_id).find((r) => !FINAL.includes(r.status));
  return {
    ...summary,
    status: cs.status,
    last_error: cs.last_error,
    reopen_count: cs.reopen_count,
    active_investigation_id: active?.investigation_id ?? null,
    updated_at: cs.updated_at,
  };
};

export const applyMockCaseList = (list) => list.map(applyMockCaseSummary);

// CaseDetail also gets investigation_ids (newest first), proposals and rechecks
export const applyMockCase = (detail) => {
  if (!db.cases.has(detail.case_id)) return detail;
  return {
    ...detail,
    ...applyMockCaseSummary(detail),
    investigation_ids: runsOf(detail.case_id).reverse().map((r) => r.investigation_id),
    proposals: [...db.proposals.values()].filter((p) => p.case_id === detail.case_id).map(clone),
    rechecks: [...db.rechecks.values()].filter((r) => r.case_id === detail.case_id).map(clone),
  };
};

// GET /domain/cases/{id}/audit → AuditEntry[], oldest first
// opened_at: CaseDetail.opened_at, to show the monitor's opening row
export const mockListAudit = async (caseId, { user, opened_at = null } = {}) => {
  await delay(150);
  requireUser(user);
  requireCase(caseId, user);
  const rows = db.audit.filter((a) => a.case_id === caseId).map(clone);
  if (opened_at) {
    rows.unshift({
      audit_id: 'AUD-000000', case_id: caseId, actor_id: 'svc_monitor', actor_role: 'service',
      action: 'case.opened', proposal_id: null, version: null, request_id: 'mock-req-0000', at: opened_at,
    });
  }
  return rows;
};

// GET /domain/cases/{id}/merchant-replies → MerchantReply[]
export const mockListMerchantReplies = async (caseId, { user } = {}) => {
  await delay(150);
  requireUser(user);
  requireCase(caseId, user);
  return [...db.replies.values()]
    .filter((r) => db.proposals.get(r.proposal_id)?.case_id === caseId)
    .map(clone);
};

// GET /domain/cases/{id}/rechecks → Recheck[]
export const mockListRechecks = async (caseId, { user } = {}) => {
  await delay(150);
  requireUser(user);
  requireCase(caseId, user);
  return [...db.rechecks.values()].filter((r) => r.case_id === caseId).map(clone);
};

// GET /domain/evidence/{id} → Evidence
export const mockGetEvidence = async (evidenceId, { user } = {}) => {
  await delay(150);
  requireUser(user);
  let found = EVIDENCE[evidenceId];
  if (!found && evidenceId.startsWith('EV-RPL-')) {
    const reply = [...db.replies.values()].find((r) => r.evidence_id === evidenceId);
    if (reply) found = replyToEvidence(reply, caseStore(db.proposals.get(reply.proposal_id).case_id));
  }
  if (!found || !canSeeStore(user, found.store_id)) {
    throw mockError(404, 'NOT_FOUND', `Evidence ${evidenceId} was not found.`);
  }
  return clone(found);
};


// ═══════════════════════════════════════════════════════════════════
// 8. Domain — proposals, decisions, replies, rechecks
// ═══════════════════════════════════════════════════════════════════
const findProposal = (id, user) => {
  const proposal = db.proposals.get(id);
  if (!proposal || !canSeeStore(user, caseStore(proposal.case_id))) {
    throw mockError(404, 'NOT_FOUND', `Proposal ${id} not found.`);
  }
  return proposal;
};

const scenarioOfProposal = (proposal) => db.investigations.get(proposal.investigation_id).scenario;

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
  audit(proposal.case_id, user, 'proposal.edited', { proposal_id: proposalId, version: proposal.version });
  save();
  return clone(proposal);
};

// POST /domain/proposals/{id}/decision { version, decision, note } → Proposal
// Approving dispatches in the same step. An approved action also schedules its recheck.
// No resume here — for a question the UI calls resume next; an action needs none.
export const mockDecideProposal = async (proposalId, { version, decision, note = null }, { user, idempotencyKey } = {}) => {
  await delay(300);
  requireAnalyst(user);

  const result = await withIdempotency(`decision:${proposalId}`, idempotencyKey, async () => {
    const proposal = findProposal(proposalId, user);
    const wanted = decision === 'approve' ? 'approved' : 'rejected';
    const isQuestion = proposal.kind === 'merchant_question';

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

    if (wanted === 'approved' && db.failNextDispatch) {
      db.failNextDispatch = false;
      audit(proposal.case_id, user, 'dispatch.failed', { proposal_id: proposalId, version });
      save();
      throw mockError(502, 'DISPATCH_FAILED', `Mock dispatch for ${proposalId} failed. The proposal stays pending.`);
    }

    Object.assign(proposal, {
      status: wanted,
      decided_by: user.user_id ?? 'USR-001',
      decided_at: now(),
      decision_note: note,
    });
    audit(proposal.case_id, user, `proposal.${wanted}`, { proposal_id: proposalId, version });

    if (wanted === 'rejected') {
      // Question: the agent continues once resumed. Action: the case goes to an analyst.
      setCase(proposal.case_id, { status: isQuestion ? 'investigating' : 'analyst_review' });
      return clone(proposal);
    }

    db.seq.dsp += 1;
    proposal.dispatch = {
      dispatch_id: `DSP-${pad(db.seq.dsp, 6)}`,
      status: 'dispatched',
      channel: isQuestion ? 'mock_merchant' : 'mock_team_queue',
      owner_team: isQuestion ? 'merchant' : proposal.content.owner_team,
      dispatched_at: proposal.decided_at,
    };
    audit(proposal.case_id, user, 'dispatch.sent', { proposal_id: proposalId, version });

    if (isQuestion) {
      setCase(proposal.case_id, { status: 'awaiting_merchant' });
    } else {
      db.seq.rck += 1;
      const recheck = buildScheduledRecheck(scenarioOfProposal(proposal), {
        recheck_id: `RCK-${pad(db.seq.rck, 4)}`,
        proposal,
        dispatched_at: proposal.dispatch.dispatched_at,
      });
      db.rechecks.set(recheck.recheck_id, recheck);
      audit(proposal.case_id, user, 'recheck.scheduled', { proposal_id: proposalId });
      setCase(proposal.case_id, { status: 'action_dispatched' });
    }
    return clone(proposal);
  });
  save();
  return result;
};

// One reply per question. actor: the analyst (User), or a service ID when the
// reply came into the system by itself.
const saveReply = (proposal, outcome, text, actor) => {
  db.seq.rpl += 1;
  const created = {
    evidence_id: `EV-RPL-${pad(db.seq.rpl, 6)}`,
    proposal_id: proposal.proposal_id,
    outcome,
    text: outcome === 'replied' ? text.trim() : null,
    recorded_by: typeof actor === 'string' ? actor : (actor.user_id ?? 'USR-001'),
    recorded_at: now(),
  };
  db.replies.set(proposal.proposal_id, created);
  audit(proposal.case_id, actor, 'merchant_reply.recorded', { proposal_id: proposal.proposal_id });
  return created;
};

// POST /domain/proposals/{id}/merchant-reply { outcome, text } → 201 MerchantReply
// The UI uses it only for "No reply"; replies arrive by themselves (see resume).
// Does not resume the investigation — the UI calls resume next.
export const mockRecordReply = async (proposalId, { outcome, text = null }, { user, idempotencyKey } = {}) => {
  await delay(300);
  requireAnalyst(user);

  const reply = await withIdempotency(`reply:${proposalId}`, idempotencyKey, async () => {
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

    return clone(saveReply(proposal, outcome, text, user));
  });
  save();
  return reply;
};

// POST /domain/rechecks/{id}/run → Recheck (demo trigger; normally on scheduled_for)
// improved → closed · insufficient_data → paused
// not_improved → reopened the first time, analyst_review the second
export const mockRunRecheck = async (recheckId, { user, idempotencyKey } = {}) => {
  await delay(400);
  requireAnalyst(user);

  const result = await withIdempotency(`recheck:${recheckId}`, idempotencyKey, async () => {
    const recheck = db.rechecks.get(recheckId);
    if (!recheck || !canSeeStore(user, caseStore(recheck.case_id))) {
      throw mockError(404, 'NOT_FOUND', `Recheck ${recheckId} not found.`);
    }
    if (recheck.status !== 'scheduled') {
      throw mockError(409, 'RECHECK_ALREADY_RUN', `Recheck ${recheckId} already has a result.`);
    }

    const proposal = db.proposals.get(recheck.proposal_id);
    const scenarioName = scenarioOfProposal(proposal);
    const status = db.nextRecheck ?? defaultRecheckOutcome(scenarioName);
    db.nextRecheck = null;

    const done = runScheduledRecheck(recheck, scenarioName, status, {
      dispatched_at: proposal.dispatch.dispatched_at,
      ran_at: now(),
    });
    db.rechecks.set(recheckId, done);
    audit(recheck.case_id, user, `recheck.${status}`, { proposal_id: recheck.proposal_id });

    const cs = caseState(recheck.case_id);
    if (status === 'improved') setCase(recheck.case_id, { status: 'closed' });
    else if (status === 'insufficient_data') setCase(recheck.case_id, { status: 'paused' });
    else if (cs.reopen_count === 0) {
      setCase(recheck.case_id, { status: 'reopened', reopen_count: 1, reopened_from: proposal.investigation_id });
    } else setCase(recheck.case_id, { status: 'analyst_review' });

    return clone(done);
  });
  save();
  return result;
};


// ═══════════════════════════════════════════════════════════════════
// 9. Dev console helper — window.__mocks
// ═══════════════════════════════════════════════════════════════════
if (typeof window !== 'undefined' && import.meta.env?.DEV) {
  window.__mocks = {
    failNextStart,
    failNextDispatch,
    nextRecheck: setNextRecheck,
    reset: resetMocks,
    db: () => db,
  };
}

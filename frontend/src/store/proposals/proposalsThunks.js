// [13a] Proposal thunks — /domain/proposals (Domain Service, C-03)
// A proposal is either a merchant question (D-05) or the recommended action.
// Mock branch when USE_MOCKS: C-03 hasn't built these routes yet.
//
// Every write rejects with { message, code, noResponse }:
//   code        contract error code, or null (api/errors.js getErrorCode)
//   noResponse  true when the request never got an answer — the caller may retry
//               with the SAME Idempotency-Key (hooks/useIdempotencyKey.js)


// ═══════════════════════════════════════════════════════════════════
// 1. Imports
// ═══════════════════════════════════════════════════════════════════
import { createAsyncThunk } from '@reduxjs/toolkit';
import api from '../../api/axios';
import { getErrorCode, getErrorMessage } from '../../api/errors';
import { USE_MOCKS } from '../../api/mockAuth';
import {
  mockGetProposal,
  mockEditProposal,
  mockDecideProposal,
  mockRecordReply,
  mockListMerchantReplies,
} from '../../api/mocks/mockInvestigations';
import { fetchCase } from '../cases/casesThunks';


// ═══════════════════════════════════════════════════════════════════
// 2. Helpers
// ═══════════════════════════════════════════════════════════════════
// Wording for the codes a decision screen reacts to (ui-workflow.md v0.3
// "When a call is refused"). Other codes use api/errors.js.
const DECISION_MESSAGES = {
  STALE_VERSION: 'Someone edited it. Review the new version before deciding.',
  ALREADY_DECIDED: 'Already decided by someone else.',
  DISPATCH_FAILED: 'Send failed. The proposal is still pending — approve again.',
  REPLY_EXISTS: 'A reply was already recorded for this question.',
  NOT_DISPATCHED: "This question wasn't sent to the merchant, so there is no reply to record.",
};

const toActionError = (err, fallback) => {
  const code = getErrorCode(err);
  return {
    code,
    message: DECISION_MESSAGES[code] ?? getErrorMessage(err, fallback),
    noResponse: !err?.response,
  };
};

const userOf = (getState) => ({ user: getState().auth.user });


// ═══════════════════════════════════════════════════════════════════
// 3. fetchProposal — GET /domain/proposals/{proposal_id}
// ═══════════════════════════════════════════════════════════════════
// → contract Proposal. Also re-run after STALE_VERSION / ALREADY_DECIDED.
export const fetchProposal = createAsyncThunk(
  'proposals/fetchOne',
  async (proposalId, { getState, rejectWithValue }) => {
    try {
      if (USE_MOCKS) return await mockGetProposal(proposalId, userOf(getState));
      const { data } = await api.get(`/domain/proposals/${encodeURIComponent(proposalId)}`);
      return data;
    } catch (err) {
      return rejectWithValue(getErrorMessage(err, 'Could not load the proposal'));
    }
  },
  {
    // Don't stack requests for the same proposal
    condition: (proposalId, { getState }) => getState().proposals.fetchStatusById[proposalId] !== 'loading',
  },
);


// ═══════════════════════════════════════════════════════════════════
// 4. editProposal — POST /domain/proposals/{id}/versions { content }
// ═══════════════════════════════════════════════════════════════════
// → 201 Proposal with the next version. Analysts only; only while pending.
// ALREADY_DECIDED → someone decided first: reload the proposal and the case.
export const editProposal = createAsyncThunk(
  'proposals/edit',
  async ({ id, content }, { getState, dispatch, rejectWithValue }) => {
    try {
      if (USE_MOCKS) return await mockEditProposal(id, { content }, userOf(getState));
      const { data } = await api.post(`/domain/proposals/${encodeURIComponent(id)}/versions`, { content });
      return data;
    } catch (err) {
      const error = toActionError(err, 'Could not save the edit');
      if (error.code === 'ALREADY_DECIDED') {
        dispatch(fetchProposal(id));
        const caseId = getState().proposals.byId[id]?.case_id;
        if (caseId) dispatch(fetchCase(caseId));
      }
      return rejectWithValue(error);
    }
  },
);


// ═══════════════════════════════════════════════════════════════════
// 5. decideProposal — POST /domain/proposals/{id}/decision
// ═══════════════════════════════════════════════════════════════════
// Body: DecisionRequest { version, decision: 'approve' | 'reject', note }
//   version is the one the analyst saw — the server refuses an older one.
// Header: Idempotency-Key.
// → Proposal, with `dispatch` set on approve. Domain moves the case, so the case
//   is reloaded. An action needs NO resume (the run already ended); a question
//   does, which QuestionReview adds in D-05.
//
// Refusals (ui-workflow.md v0.3):
//   409 STALE_VERSION    someone edited it → reload the proposal, show the new version
//   409 ALREADY_DECIDED  someone decided   → reload the proposal and the case
//   502 DISPATCH_FAILED  send failed       → still pending, approve again
export const decideProposal = createAsyncThunk(
  'proposals/decide',
  async ({ id, version, decision, note = null, idempotencyKey }, { getState, dispatch, rejectWithValue }) => {
    const body = { version, decision, note: note?.trim() ? note.trim() : null };
    try {
      const proposal = USE_MOCKS
        ? await mockDecideProposal(id, body, { ...userOf(getState), idempotencyKey })
        : (await api.post(`/domain/proposals/${encodeURIComponent(id)}/decision`, body, {
          headers: { 'Idempotency-Key': idempotencyKey },
        })).data;

      dispatch(fetchCase(proposal.case_id));
      return proposal;
    } catch (err) {
      const error = toActionError(err, 'Could not save the decision');
      if (error.code === 'STALE_VERSION' || error.code === 'ALREADY_DECIDED') {
        dispatch(fetchProposal(id));
      }
      if (error.code === 'ALREADY_DECIDED') {
        const caseId = getState().proposals.byId[id]?.case_id;
        if (caseId) dispatch(fetchCase(caseId));
      }
      return rejectWithValue(error);
    }
  },
);


// ═══════════════════════════════════════════════════════════════════
// 6. fetchMerchantReplies — GET /domain/cases/{case_id}/merchant-replies (D-05)
// ═══════════════════════════════════════════════════════════════════
// → MerchantReply[] for the whole case; the slice files them by proposal_id.
export const fetchMerchantReplies = createAsyncThunk(
  'proposals/fetchReplies',
  async (caseId, { getState, rejectWithValue }) => {
    try {
      if (USE_MOCKS) return await mockListMerchantReplies(caseId, userOf(getState));
      const { data } = await api.get(`/domain/cases/${encodeURIComponent(caseId)}/merchant-replies`);
      return data;
    } catch (err) {
      return rejectWithValue(getErrorMessage(err, 'Could not load the merchant replies'));
    }
  },
  {
    condition: (caseId, { getState }) => getState().proposals.repliesStatusByCase[caseId] !== 'loading',
  },
);


// ═══════════════════════════════════════════════════════════════════
// 7. recordMerchantReply — POST /domain/proposals/{id}/merchant-reply (D-05)
// ═══════════════════════════════════════════════════════════════════
// Body: MerchantReplyCreate { outcome: 'replied' | 'no_reply', text }
//   text is required for 'replied', null for 'no_reply'. The analyst types or
//   pastes what the merchant said — untrusted text, always shown as plain text.
// Header: Idempotency-Key.
// → 201 MerchantReply (it is also evidence EV-RPL-…). The caller then resumes
//   the run (MerchantReplyForm) — "reply first, then resume".
//
// 409 REPLY_EXISTS → someone recorded it first: reload the replies, so the form
//   turns into "reply saved → Continue".
export const recordMerchantReply = createAsyncThunk(
  'proposals/recordReply',
  async ({ id, caseId, outcome, text, idempotencyKey }, { getState, dispatch, rejectWithValue }) => {
    const body = { outcome, text: outcome === 'replied' ? text.trim() : null };
    try {
      if (USE_MOCKS) return await mockRecordReply(id, body, { ...userOf(getState), idempotencyKey });
      const { data } = await api.post(`/domain/proposals/${encodeURIComponent(id)}/merchant-reply`, body, {
        headers: { 'Idempotency-Key': idempotencyKey },
      });
      return data;
    } catch (err) {
      const error = toActionError(err, 'Could not save the reply');
      if (error.code === 'REPLY_EXISTS') dispatch(fetchMerchantReplies(caseId));
      return rejectWithValue(error);
    }
  },
);

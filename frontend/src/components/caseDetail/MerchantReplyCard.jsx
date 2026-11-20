// [10v] MerchantReplyCard — box 7: confirm the merchant answered, or that they didn't
// Step 4 (awaiting_merchant). The question went out by mock dispatch. The
// merchant's answer comes into the system by itself — the analyst never types
// it. The analyst only confirms it arrived, and the agent resumes and reads the
// reply from Domain itself.
//
//   Waiting for the merchant
//   [No reply]  [Merchant replied — continue]
//
// "Merchant replied" → resume only.
// "No reply"         → record no_reply, then resume (ui-workflow.md "Steps 4 → 2").
// Once a reply (or no_reply) is in Domain but the run hasn't continued, the card
// becomes a ContinueBox (caseSteps.needsResume) — also after a reload.


// ═══════════════════════════════════════════════════════════════════
// 1. Imports
// ═══════════════════════════════════════════════════════════════════
import { useEffect } from 'react';
import { useDispatch, useSelector } from 'react-redux';
import { fetchMerchantReplies, recordMerchantReply } from '../../store/proposals/proposalsThunks';
import { selectProposalWrite, selectReply } from '../../store/proposals/proposalsSelectors';
import { selectCaseDetail } from '../../store/cases/casesSelectors';
import { selectIsAnalyst } from '../../store/auth/authSelectors';
import useIdempotencyKey from '../../hooks/useIdempotencyKey';
import useResume from '../../hooks/useResume';
import ContinueBox from './ContinueBox';
import { needsResume, runQuestions } from './caseSteps';


// ═══════════════════════════════════════════════════════════════════
// 2. Which question is waiting for an answer
// ═══════════════════════════════════════════════════════════════════
// The mock keeps pending_proposal_id on the question while awaiting_merchant
// (d03 plan, "需要确认": to confirm with Member 2). If the real agent clears it,
// fall back to this run's latest approved question.
const useOpenQuestion = (investigation) => {
  const caseDetail = useSelector((state) => selectCaseDetail(state, investigation.case_id));
  const latest = useSelector((state) => state.proposals.byId);
  const questions = runQuestions(investigation, caseDetail, latest);
  if (investigation.pending_proposal_id) {
    return questions.find((q) => q.proposal_id === investigation.pending_proposal_id)
      ?? { proposal_id: investigation.pending_proposal_id, status: 'approved' };
  }
  return [...questions].reverse().find((q) => q.status === 'approved') ?? null;
};


// ═══════════════════════════════════════════════════════════════════
// 3. MerchantReplyCard component
// ═══════════════════════════════════════════════════════════════════
const MerchantReplyCard = ({ investigation }) => {
  const dispatch = useDispatch();
  const question = useOpenQuestion(investigation);
  const questionId = question?.proposal_id;
  const reply = useSelector((state) => selectReply(state, questionId));
  const write = useSelector((state) => selectProposalWrite(state, questionId));
  const isAnalyst = useSelector(selectIsAnalyst);
  const { keyFor, settle } = useIdempotencyKey();
  const { resume, resuming, error: resumeError } = useResume(investigation.investigation_id);

  // Load recorded replies: a reply already in Domain shows as "arrived → Continue"
  useEffect(() => {
    dispatch(fetchMerchantReplies(investigation.case_id));
  }, [dispatch, investigation.case_id]);

  if (!question) {
    return <p className='muted'>Waiting for the merchant. The question isn't loaded yet.</p>;
  }

  // ── 3a. A reply (or no_reply) is in Domain, the run hasn't continued ──
  if (needsResume(investigation, question, reply)) {
    return (
      <ContinueBox
        investigationId={investigation.investigation_id}
        saved={reply.outcome === 'replied' ? "The merchant's reply" : '"No reply"'}
      />
    );
  }

  if (!isAnalyst) {
    return (
      <div className='reply-form'>
        <h3>Waiting for the merchant</h3>
        <p className='muted'>An analyst continues the investigation once the merchant has answered.</p>
      </div>
    );
  }

  // ── 3b. Confirm the reply arrived, or record no reply ─────────────
  const savingNoReply = write?.kind === 'reply' && write.status === 'loading';
  const writeError = write?.kind === 'reply' && write.status === 'failed' ? write.error : null;
  const busy = savingNoReply || resuming;

  const recordNoReply = async () => {
    if (!window.confirm('Record that the merchant did not reply? The agent continues without an answer.')) return;

    const result = await dispatch(recordMerchantReply({
      id: questionId,
      caseId: investigation.case_id,
      outcome: 'no_reply',
      text: null,
      idempotencyKey: keyFor('no_reply'),
    }));
    if (recordMerchantReply.fulfilled.match(result)) {
      settle(null);
      await resume(); // if this fails, needsResume turns the card into a ContinueBox
    } else {
      settle(result.payload);
    }
  };

  const error = writeError ?? resumeError;
  return (
    <div className='reply-form'>
      <h3>Waiting for the merchant</h3>
      <p className='muted'>
        The merchant's answer comes into the system by itself. Once it has arrived, confirm it here and the
        agent reads it and continues. If the merchant doesn't answer, record "No reply".
      </p>
      <div className='decision-buttons'>
        <button type='button' className='button-secondary' onClick={recordNoReply} disabled={busy}>
          {savingNoReply ? 'Saving…' : 'No reply'}
        </button>
        <button type='button' onClick={resume} disabled={busy}>
          {resuming ? 'Continuing…' : 'Merchant replied — continue'}
        </button>
      </div>
      {error && (
        <p className='error' role='alert'>
          {error.noResponse ? "Couldn't reach the server. Try again — it won't be done twice." : error.message}
        </p>
      )}
    </div>
  );
};


// ═══════════════════════════════════════════════════════════════════
// 4. Export
// ═══════════════════════════════════════════════════════════════════
export default MerchantReplyCard;

// [10v] MerchantReplyCard — box 7: the merchant's answer, live (D-05)
// Step 4 (awaiting_merchant). The question went out by mock dispatch. The
// merchant's answer comes into Domain by itself — the analyst never types it.
// The card watches Domain for it (usePollMerchantReply, every 3 s) and changes
// as soon as it arrives:
//
//   No reply yet                      Reply arrived
//   ┌ Waiting for the merchant ─┐     ┌ The merchant replied ─────────┐
//   │ (empty) checking…         │ ──▶ │ "We changed the bagging …"    │
//   │              [No reply]   │     │      [Confirm and continue]   │
//   └───────────────────────────┘     └───────────────────────────────┘
//
// "Confirm and continue" → resume only: the agent reads the reply from Domain.
// "No reply"             → record no_reply, then resume (ui-workflow.md "Steps 4 → 2").
// no_reply recorded but the resume failed (or the page reloaded) → ContinueBox.


// ═══════════════════════════════════════════════════════════════════
// 1. Imports
// ═══════════════════════════════════════════════════════════════════
import { useDispatch, useSelector } from 'react-redux';
import { recordMerchantReply } from '../../store/proposals/proposalsThunks';
import { selectProposalWrite, selectReply, selectRepliesStatus } from '../../store/proposals/proposalsSelectors';
import { selectCaseDetail } from '../../store/cases/casesSelectors';
import { selectIsAnalyst } from '../../store/auth/authSelectors';
import { formatDateTime } from '../../api/format';
import useIdempotencyKey from '../../hooks/useIdempotencyKey';
import usePollMerchantReply from '../../hooks/usePollMerchantReply';
import useResume from '../../hooks/useResume';
import EvidenceLink from '../common/EvidenceLink';
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
// 3. The two states of the card
// ═══════════════════════════════════════════════════════════════════
const ErrorLine = ({ error }) =>
  error ? (
    <p className='error' role='alert'>
      {error.noResponse ? "Couldn't reach the server. Try again — it won't be done twice." : error.message}
    </p>
  ) : null;

// ── 3a. The reply arrived: show it, analyst confirms → resume ───────
// Plain text: untrusted merchant words, never rendered as HTML.
const ReplyArrived = ({ investigation, reply, isAnalyst, timeZone }) => {
  const { resume, resuming, error } = useResume(investigation.investigation_id);

  return (
    <div className='reply-form reply-arrived' role='status' aria-live='polite'>
      <h3>The merchant replied</h3>
      <p className='muted'>
        {formatDateTime(reply.recorded_at, timeZone)} · <EvidenceLink id={reply.evidence_id} />
      </p>
      <blockquote className='reply-text'>{reply.text}</blockquote>
      {isAnalyst ? (
        <>
          <p className='muted'>Confirm to let the agent read this reply and continue the investigation.</p>
          <div className='decision-buttons'>
            <button type='button' onClick={resume} disabled={resuming}>
              {resuming ? 'Continuing…' : 'Confirm and continue'}
            </button>
          </div>
        </>
      ) : (
        <p className='muted'>Waiting for an analyst to confirm the reply.</p>
      )}
      <ErrorLine error={error} />
    </div>
  );
};

// ── 3b. No reply yet: empty, checking; analyst may record "No reply" ─
const WaitingForReply = ({ investigation, questionId, isAnalyst, checkFailed }) => {
  const dispatch = useDispatch();
  const write = useSelector((state) => selectProposalWrite(state, questionId));
  const { keyFor, settle } = useIdempotencyKey();
  const { resume, resuming, error: resumeError } = useResume(investigation.investigation_id);

  const savingNoReply = write?.kind === 'reply' && write.status === 'loading';
  const writeError = write?.kind === 'reply' && write.status === 'failed' ? write.error : null;

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

  return (
    <div className='reply-form'>
      <h3>Waiting for the merchant</h3>
      <div className='reply-empty' aria-live='polite'>
        <span className='reply-pulse' aria-hidden='true' />
        No reply yet. It shows up here as soon as it arrives.
      </div>
      {checkFailed && <p className='muted'>Couldn't check for a reply just now. Trying again…</p>}
      {isAnalyst ? (
        <div className='decision-buttons'>
          <button type='button' className='button-secondary' onClick={recordNoReply} disabled={savingNoReply || resuming}>
            {savingNoReply ? 'Saving…' : resuming ? 'Continuing…' : 'No reply'}
          </button>
        </div>
      ) : (
        <p className='muted'>An analyst continues the investigation once the merchant has answered.</p>
      )}
      <ErrorLine error={writeError ?? resumeError} />
    </div>
  );
};


// ═══════════════════════════════════════════════════════════════════
// 4. MerchantReplyCard component
// ═══════════════════════════════════════════════════════════════════
const MerchantReplyCard = ({ investigation, timeZone }) => {
  const question = useOpenQuestion(investigation);
  const questionId = question?.proposal_id;
  const reply = useSelector((state) => selectReply(state, questionId));
  const repliesStatus = useSelector((state) => selectRepliesStatus(state, investigation.case_id));
  const isAnalyst = useSelector(selectIsAnalyst);

  // Watch Domain until this question has a reply (or no_reply)
  usePollMerchantReply(investigation.case_id, Boolean(questionId) && !reply);

  if (!question) {
    return <p className='muted'>Waiting for the merchant. The question isn't loaded yet.</p>;
  }

  if (reply?.outcome === 'replied') {
    return <ReplyArrived investigation={investigation} reply={reply} isAnalyst={isAnalyst} timeZone={timeZone} />;
  }

  // "No reply" saved, the run hasn't continued
  if (needsResume(investigation, question, reply)) {
    return <ContinueBox investigationId={investigation.investigation_id} saved='"No reply"' />;
  }

  return (
    <WaitingForReply
      investigation={investigation}
      questionId={questionId}
      isAnalyst={isAnalyst}
      checkFailed={repliesStatus === 'failed'}
    />
  );
};


// ═══════════════════════════════════════════════════════════════════
// 5. Export
// ═══════════════════════════════════════════════════════════════════
export default MerchantReplyCard;

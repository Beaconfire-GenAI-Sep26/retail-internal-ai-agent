// [10v] MerchantReplyForm — box 7: what the merchant answered, or that they didn't
// Step 4 (awaiting_merchant). The question went out by mock dispatch; the analyst
// types or pastes the merchant's answer here. Then the run continues:
// reply first, then resume (ui-workflow.md v0.3, "Steps 4 → 2").
//
//   The merchant's reply
//   [ textarea ]
//   [No reply]  [Save reply]
//
// The text is untrusted: the agent reads it as quoted data, and the page only
// ever shows it as plain text. Once a reply is saved but the run hasn't continued,
// the form becomes a ContinueBox (caseSteps.needsResume) — also after a reload.


// ═══════════════════════════════════════════════════════════════════
// 1. Imports
// ═══════════════════════════════════════════════════════════════════
import { useEffect, useState } from 'react';
import { useDispatch, useSelector } from 'react-redux';
import { fetchMerchantReplies, recordMerchantReply } from '../../store/proposals/proposalsThunks';
import { selectProposalWrite, selectReply } from '../../store/proposals/proposalsSelectors';
import { selectCaseDetail } from '../../store/cases/casesSelectors';
import { selectIsAnalyst } from '../../store/auth/authSelectors';
import useIdempotencyKey from '../../hooks/useIdempotencyKey';
import useResume from '../../hooks/useResume';
import ContinueBox from './ContinueBox';
import { needsResume, runQuestions } from './caseSteps';

const MAX_REPLY = 4000;


// ═══════════════════════════════════════════════════════════════════
// 2. Which question this reply answers
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
// 3. MerchantReplyForm component
// ═══════════════════════════════════════════════════════════════════
const MerchantReplyForm = ({ investigation }) => {
  const dispatch = useDispatch();
  const question = useOpenQuestion(investigation);
  const questionId = question?.proposal_id;
  const reply = useSelector((state) => selectReply(state, questionId));
  const write = useSelector((state) => selectProposalWrite(state, questionId));
  const isAnalyst = useSelector(selectIsAnalyst);
  const { keyFor, settle } = useIdempotencyKey();
  const { resume } = useResume(investigation.investigation_id);
  const [text, setText] = useState('');

  // Load recorded replies: a reply saved before a reload must show as saved
  useEffect(() => {
    dispatch(fetchMerchantReplies(investigation.case_id));
  }, [dispatch, investigation.case_id]);

  if (!question) {
    return <p className='muted'>Waiting for the merchant. The question isn't loaded yet.</p>;
  }

  // ── 3a. Saved, but the run hasn't continued → resume only ────────
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
        <p className='muted'>Only analysts can record the merchant's reply.</p>
      </div>
    );
  }

  // ── 3b. The form ─────────────────────────────────────────────────
  const saving = write?.kind === 'reply' && write.status === 'loading';
  const error = write?.kind === 'reply' && write.status === 'failed' ? write.error : null;

  const record = async (outcome) => {
    if (outcome === 'no_reply'
      && !window.confirm('Record that the merchant did not reply? The agent continues without an answer.')) return;

    const result = await dispatch(recordMerchantReply({
      id: questionId,
      caseId: investigation.case_id,
      outcome,
      text,
      idempotencyKey: keyFor(outcome),
    }));
    if (recordMerchantReply.fulfilled.match(result)) {
      settle(null);
      setText('');
      await resume(); // if this fails, needsResume turns the form into a ContinueBox
    } else {
      settle(result.payload);
    }
  };

  const id = `reply-${questionId}`;
  return (
    <form className='reply-form' onSubmit={(e) => { e.preventDefault(); record('replied'); }}>
      <h3>Waiting for the merchant</h3>
      <p className='muted'>When the merchant answers, enter what they said. If they don't answer, record "No reply".</p>
      <label htmlFor={id}>The merchant's reply</label>
      <textarea
        id={id}
        rows={4}
        value={text}
        maxLength={MAX_REPLY}
        onChange={(e) => setText(e.target.value)}
        disabled={saving}
        placeholder="Paste or type the merchant's answer"
      />
      <div className='decision-buttons'>
        <button type='button' className='button-secondary' onClick={() => record('no_reply')} disabled={saving}>
          No reply
        </button>
        <button type='submit' disabled={saving || !text.trim()}>
          {saving ? 'Saving…' : 'Save reply'}
        </button>
      </div>
      {error && (
        <p className='error' role='alert'>
          {error.noResponse ? "Couldn't reach the server. Try again — it won't be saved twice." : error.message}
        </p>
      )}
    </form>
  );
};


// ═══════════════════════════════════════════════════════════════════
// 4. Export
// ═══════════════════════════════════════════════════════════════════
export default MerchantReplyForm;

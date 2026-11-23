// [10t] QuestionReview — box 6: a question the agent wants to send to the merchant
// The agent can't reach the merchant itself. It drafts a question, pauses
// (awaiting_approval), and an analyst edits, approves or rejects it.
//
// Two modes:
//   review   step 3, in the shared spot. Edit · Reject · Approve and send.
//            Decide first, then resume (ui-workflow.md v0.3). If the decision
//            worked but the resume didn't, a "Continue" box offers the resume
//            only — worked out from the data (needsResume), so a reload keeps it.
//   history  read-only, from step 4 until the run ends: the question, the
//            decision, where it was sent, and the merchant's reply.
//
//   Reject → the agent continues without asking (usually ends unsure).
//   Approve → sent to the merchant; the run waits for the reply (step 4).


// ═══════════════════════════════════════════════════════════════════
// 1. Imports
// ═══════════════════════════════════════════════════════════════════
import { useEffect, useState } from 'react';
import { useDispatch, useSelector } from 'react-redux';
import { fetchProposal, editProposal, fetchMerchantReplies } from '../../store/proposals/proposalsThunks';
import { proposalWriteCleared } from '../../store/proposals/proposalsSlice';
import {
  selectProposal,
  selectProposalFetchStatus,
  selectProposalFetchError,
  selectProposalWrite,
} from '../../store/proposals/proposalsSelectors';
import { selectCaseDetail } from '../../store/cases/casesSelectors';
import { selectIsAnalyst } from '../../store/auth/authSelectors';
import useResume from '../../hooks/useResume';
import Pill from '../common/Pill';
import Chapter from '../common/Chapter';
import EvidenceLink, { EvidenceLinks } from '../common/EvidenceLink';
import DecisionControls from './DecisionControls';
import ContinueBox from './ContinueBox';
import { needsResume, runQuestions } from './caseSteps';
import { formatDateTime } from '../../api/format';


// ═══════════════════════════════════════════════════════════════════
// 2. Pieces
// ═══════════════════════════════════════════════════════════════════
const STATUS_PILLS = {
  pending: <Pill tone='warn'>Waiting for you</Pill>,
  approved: <Pill tone='ok'>Sent to the merchant</Pill>,
  rejected: <Pill tone='bad'>Not sent</Pill>,
};

// The question itself — merchant-facing text, shown as plain text
const QuestionText = ({ proposal }) => (
  <>
    <blockquote className='question-text'>{proposal.content.question_text}</blockquote>
    <p className='muted'>Why the agent asks: {proposal.content.why_asked}</p>
    <EvidenceLinks label='Evidence' ids={proposal.evidence_ids} />
  </>
);

// Edit the question text → a new version. why_asked is the agent's reasoning,
// not sent to the merchant, so it isn't editable.
const QuestionEdit = ({ proposal, onDone }) => {
  const dispatch = useDispatch();
  const write = useSelector((state) => selectProposalWrite(state, proposal.proposal_id));
  const [text, setText] = useState(proposal.content.question_text);
  const saving = write?.kind === 'edit' && write.status === 'loading';
  const error = write?.kind === 'edit' && write.status === 'failed' ? write.error : null;

  const save = async (e) => {
    e.preventDefault();
    const result = await dispatch(editProposal({
      id: proposal.proposal_id,
      content: { ...proposal.content, question_text: text.trim() },
    }));
    if (editProposal.fulfilled.match(result)) onDone();
  };

  const cancel = () => {
    dispatch(proposalWriteCleared(proposal.proposal_id));
    onDone();
  };

  return (
    <form className='proposal-edit' onSubmit={save}>
      <label>
        Question for the merchant
        <textarea rows={3} value={text} onChange={(e) => setText(e.target.value)} disabled={saving} />
      </label>
      <div className='decision-buttons'>
        <button type='button' className='button-secondary' onClick={cancel} disabled={saving}>Cancel</button>
        <button type='submit' disabled={saving || !text.trim() || text.trim() === proposal.content.question_text}>
          {saving ? 'Saving…' : `Save as version ${proposal.version + 1}`}
        </button>
      </div>
      {error && <p className='error' role='alert'>{error.message}</p>}
    </form>
  );
};

// Who decided, when, and where it went
const DecisionLine = ({ proposal, timeZone }) => {
  if (proposal.status === 'pending') return null;
  const verb = proposal.status === 'approved' ? 'Approved' : 'Rejected';
  return (
    <div className='decision-outcome'>
      <p>
        <strong>{verb}</strong> by {proposal.decided_by} · {formatDateTime(proposal.decided_at, timeZone)}
        {proposal.dispatch && <span className='muted'> · sent · {proposal.dispatch.dispatch_id}</span>}
      </p>
      {proposal.status === 'rejected' && <p className='muted'>Not sent. The agent continues without asking.</p>}
      {proposal.decision_note && <p className='decision-note'>“{proposal.decision_note}”</p>}
    </div>
  );
};


// ═══════════════════════════════════════════════════════════════════
// 3. Review mode — step 3, in the shared spot
// ═══════════════════════════════════════════════════════════════════
const QuestionDecide = ({ investigation, timeZone }) => {
  const dispatch = useDispatch();
  const proposalId = investigation.pending_proposal_id;
  const proposal = useSelector((state) => selectProposal(state, proposalId));
  const fetchStatus = useSelector((state) => selectProposalFetchStatus(state, proposalId));
  const fetchError = useSelector((state) => selectProposalFetchError(state, proposalId));
  const isAnalyst = useSelector(selectIsAnalyst);
  const { resume } = useResume(investigation.investigation_id);
  const [editing, setEditing] = useState(false);

  useEffect(() => {
    if (proposalId) dispatch(fetchProposal(proposalId));
  }, [dispatch, proposalId]);

  if (!proposal) {
    return (
      <div className='question-review'>
        {fetchStatus === 'failed' ? (
          <div className='error' role='alert'>
            <p>{fetchError}</p>
            <button type='button' onClick={() => dispatch(fetchProposal(proposalId))}>Retry</button>
          </div>
        ) : (
          <p className='muted'>Loading the question…</p>
        )}
      </div>
    );
  }

  const pending = proposal.status === 'pending';

  // Same frame as the recommended action: red band while it waits for the analyst
  return (
    <div className={`recommendation-review question-review recommendation-${proposal.status}`}>
      <div className='recommendation-band'>
        <h3>
          <svg viewBox='0 0 24 24' aria-hidden='true' fill='none' stroke='currentColor' strokeWidth='2.4'
            strokeLinecap='round' strokeLinejoin='round'>
            <path d='M21 12a8 8 0 0 1-11.6 7.1L4 20l1-4.6A8 8 0 1 1 21 12z' />
          </svg>
          The agent wants to ask the merchant
          {pending && <span className='recommendation-band-note'> · nothing is sent until you approve</span>}
        </h3>
        <span className='recommendation-band-meta'>
          {!pending && STATUS_PILLS[proposal.status]} version {proposal.version}
        </span>
      </div>

      <div className='recommendation-body'>
        {editing && pending ? <QuestionEdit proposal={proposal} onDone={() => setEditing(false)} /> : <QuestionText proposal={proposal} />}

        {pending && (
          <DecisionControls
            proposal={proposal}
            approveLabel='Approve and send'
            rejectLabel='Reject — continue without asking'
            afterDecided={resume}
            disabled={editing}
            extra={isAnalyst && !editing && (
              <button type='button' className='button-secondary' onClick={() => setEditing(true)}>Edit</button>
            )}
          />
        )}

        {/* Decided, but the run is still waiting: only the resume is left */}
        {!pending && (
          <>
            <DecisionLine proposal={proposal} timeZone={timeZone} />
            {needsResume(investigation, proposal) && (
              <ContinueBox investigationId={investigation.investigation_id} saved={`Your decision (${proposal.status})`} />
            )}
          </>
        )}
      </div>
    </div>
  );
};


// ═══════════════════════════════════════════════════════════════════
// 4. History mode — read-only: the questions and replies as a conversation
// ═══════════════════════════════════════════════════════════════════
//   Agent → Merchant · approved by USR-001 · Nov 16, 9:20 AM   ← purple bubble (the agent's words)
//   Did anything change in your menu setup around Oct 30?
//   Why the agent asked: …  Evidence: EV-…
//                  Merchant · recorded by USR-001 · EV-RPL-…   ← grey bubble, right (merchant's words)
//                  We added an Extra sauce option…
// asChapter: its own chapter, folded to one line (after the run ends);
// otherwise just the thread, inside the run's card (while the run goes on).

// One question and what came back
// open: the question waiting for its reply (step 4) — MerchantReplyCard shows that
const Exchange = ({ q, reply, open = false, timeZone }) => {
  const sent = q.status === 'approved';
  const who = q.status === 'pending'
    ? 'Agent · draft'
    : `Agent → Merchant · ${sent ? 'approved' : 'rejected'} by ${q.decided_by} · ${formatDateTime(q.decided_at, timeZone)}`;
  return (
    <div className='exchange'>
      <div className={`bubble bubble-agent${sent ? '' : ' bubble-unsent'}`}>
        <span className='bubble-meta'>{who} {!sent && STATUS_PILLS[q.status]}</span>
        <blockquote>{q.content.question_text}</blockquote>
      </div>
      <div className='bubble-aside'>
        <p>Why the agent asked: {q.content.why_asked}</p>
        <EvidenceLinks label='Evidence' ids={q.evidence_ids} />
        {q.decision_note && <p className='decision-note'>Note: “{q.decision_note}”</p>}
      </div>
      {/* The merchant's answer. Plain text: untrusted merchant words. */}
      {reply && reply.outcome === 'no_reply' && (
        <p className='bubble-none'>No reply from the merchant · recorded by {reply.recorded_by} · {formatDateTime(reply.recorded_at, timeZone)}</p>
      )}
      {reply && reply.outcome === 'replied' && (
        <div className='bubble bubble-merchant'>
          <span className='bubble-meta'>
            Merchant · recorded by {reply.recorded_by} · {formatDateTime(reply.recorded_at, timeZone)} · <EvidenceLink id={reply.evidence_id} />
          </span>
          <blockquote>{reply.text}</blockquote>
        </div>
      )}
      {sent && !reply && !open && <p className='bubble-none'>Waiting for the merchant's answer.</p>}
    </div>
  );
};

const QuestionHistory = ({ investigation, timeZone, asChapter = false }) => {
  const dispatch = useDispatch();
  const caseDetail = useSelector((state) => selectCaseDetail(state, investigation.case_id));
  const latest = useSelector((state) => state.proposals.byId);
  const replies = useSelector((state) => state.proposals.repliesByProposal);
  const questions = runQuestions(investigation, caseDetail, latest);
  const askedAny = questions.length > 0;

  // The replies, for questions that were sent. Reloaded when the run moves on
  // (e.g. a reply recorded → running → completed).
  useEffect(() => {
    if (askedAny) dispatch(fetchMerchantReplies(investigation.case_id));
  }, [dispatch, askedAny, investigation.case_id, investigation.status]);

  // Step 4: the open question's reply shows in MerchantReplyCard (with its
  // confirm button), not here too. Same question the card picks.
  const openId = investigation.status === 'awaiting_merchant'
    ? (investigation.pending_proposal_id ?? [...questions].reverse().find((q) => q.status === 'approved')?.proposal_id)
    : null;

  // Only if this run asked one (ui-workflow.md v0.3 notes)
  if (questions.length === 0) return null;

  const thread = (
    <div className='question-history'>
      {questions.map((q) => (
        <Exchange
          key={q.proposal_id}
          q={q}
          // Step 4: the open question's reply shows in MerchantReplyCard below
          reply={q.proposal_id === openId ? null : replies[q.proposal_id]}
          open={q.proposal_id === openId}
          timeZone={timeZone}
        />
      ))}
    </div>
  );
  if (!asChapter) return thread;

  // Folded summary: how many questions, and how the last one ended
  const last = questions.at(-1);
  const lastReply = replies[last.proposal_id];
  let outcome = <Pill tone='bad'>Not sent</Pill>;
  if (last.status === 'approved') {
    outcome = lastReply?.outcome === 'replied' ? <Pill tone='ok'>Merchant replied</Pill> : <Pill tone='warn'>No reply</Pill>;
  }
  const count = `${questions.length} ${questions.length === 1 ? 'question' : 'questions'}`;
  return (
    <>
      <Chapter title='Merchant conversation' meta={count} />
      <details className='conversation-card'>
        <summary>
          <span>The agent asked the merchant {questions.length === 1 ? 'a question' : count}</span>
          {outcome}
          <span className='conversation-toggle' aria-hidden='true' />
        </summary>
        {thread}
      </details>
    </>
  );
};


// ═══════════════════════════════════════════════════════════════════
// 5. QuestionReview component
// ═══════════════════════════════════════════════════════════════════
// mode: 'review' (step 3) | 'history' (read-only)
// asChapter (history only): its own folded chapter instead of a thread in the run's card
const QuestionReview = ({ mode, investigation, timeZone, asChapter = false }) =>
  mode === 'review'
    ? <QuestionDecide investigation={investigation} timeZone={timeZone} />
    : <QuestionHistory investigation={investigation} timeZone={timeZone} asChapter={asChapter} />;


// ═══════════════════════════════════════════════════════════════════
// 6. Export
// ═══════════════════════════════════════════════════════════════════
export default QuestionReview;

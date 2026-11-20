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
//            decision and where it was sent. Commit 6 adds the merchant's reply.
//
//   Reject → the agent continues without asking (usually ends unsure).
//   Approve → sent to the merchant; the run waits for the reply (step 4).


// ═══════════════════════════════════════════════════════════════════
// 1. Imports
// ═══════════════════════════════════════════════════════════════════
import { useEffect, useState } from 'react';
import { useDispatch, useSelector } from 'react-redux';
import { fetchProposal, editProposal } from '../../store/proposals/proposalsThunks';
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
import { EvidenceLinks } from '../common/EvidenceLink';
import DecisionControls from './DecisionControls';
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

// Decision saved, run not continued yet → resume only
const ContinueBox = ({ investigationId, proposal }) => {
  const isAnalyst = useSelector(selectIsAnalyst);
  const { resume, resuming, error } = useResume(investigationId);

  return (
    <div className='continue-box' role='status'>
      <p>
        Your decision is saved ({proposal.status}). The agent hasn't continued yet.
      </p>
      {isAnalyst ? (
        <button type='button' onClick={resume} disabled={resuming}>
          {resuming ? 'Continuing…' : 'Continue the investigation'}
        </button>
      ) : (
        <p className='muted'>Waiting for an analyst to continue it.</p>
      )}
      {error && (
        <p className='error' role='alert'>
          {error.noResponse ? "Couldn't reach the agent. Try again." : error.message}
        </p>
      )}
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

  return (
    <div className='question-review'>
      <div className='recommendation-head'>
        <h3>The agent wants to ask the merchant</h3>
        {STATUS_PILLS[proposal.status]}
        <span className='muted'>version {proposal.version}</span>
      </div>

      {editing && pending ? <QuestionEdit proposal={proposal} onDone={() => setEditing(false)} /> : <QuestionText proposal={proposal} />}

      {pending && (
        <>
          {isAnalyst && !editing && (
            <button type='button' className='button-secondary recommendation-edit' onClick={() => setEditing(true)}>
              Edit
            </button>
          )}
          <DecisionControls
            proposal={proposal}
            approveLabel='Approve and send'
            rejectLabel='Reject — continue without asking'
            afterDecided={resume}
            disabled={editing}
          />
        </>
      )}

      {/* Decided, but the run is still waiting: only the resume is left */}
      {!pending && (
        <>
          <DecisionLine proposal={proposal} timeZone={timeZone} />
          {needsResume(investigation, proposal) && (
            <ContinueBox investigationId={investigation.investigation_id} proposal={proposal} />
          )}
        </>
      )}
    </div>
  );
};


// ═══════════════════════════════════════════════════════════════════
// 4. History mode — read-only, until the run ends
// ═══════════════════════════════════════════════════════════════════
const QuestionHistory = ({ investigation, timeZone }) => {
  const caseDetail = useSelector((state) => selectCaseDetail(state, investigation.case_id));
  const latest = useSelector((state) => state.proposals.byId);
  const questions = runQuestions(investigation, caseDetail, latest);

  // Only if this run asked one (ui-workflow.md v0.3 notes)
  if (questions.length === 0) return null;

  return (
    <div className='question-history'>
      {questions.map((q) => (
        <div key={q.proposal_id} className='question-review question-past'>
          <div className='recommendation-head'>
            <h3>Question to the merchant</h3>
            {STATUS_PILLS[q.status]}
          </div>
          <QuestionText proposal={q} />
          <DecisionLine proposal={q} timeZone={timeZone} />
        </div>
      ))}
    </div>
  );
};


// ═══════════════════════════════════════════════════════════════════
// 5. QuestionReview component
// ═══════════════════════════════════════════════════════════════════
// mode: 'review' (step 3) | 'history' (read-only)
const QuestionReview = ({ mode, investigation, timeZone }) =>
  mode === 'review'
    ? <QuestionDecide investigation={investigation} timeZone={timeZone} />
    : <QuestionHistory investigation={investigation} timeZone={timeZone} />;


// ═══════════════════════════════════════════════════════════════════
// 6. Export
// ═══════════════════════════════════════════════════════════════════
export default QuestionReview;

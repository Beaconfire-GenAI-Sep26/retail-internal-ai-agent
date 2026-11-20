// [10r] RecommendationReview — box 9: the recommended action, and the analyst's decision
// Shown under ResultPanel once a run completes (getCaseView.showRecommendation).
// The action is a Domain proposal (kind intervention / handoff): result.proposal_id.
//
// States (ui-workflow.md v0.3 "Action box states"):
//   review     Edit · Reject · Approve and send
//   approved   Approved by … · sent to … · DSP-…
//   rejected   Nothing is sent. The case goes to analyst review.
//   send failed (502 DISPATCH_FAILED)  still pending — approve again
//
// Deciding reloads the case (decideProposal), which moves the page to step 6
// (action sent) or analyst review. No resume: the run has already ended.


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
import { selectIsAnalyst } from '../../store/auth/authSelectors';
import Pill from '../common/Pill';
import { EvidenceLinks } from '../common/EvidenceLink';
import DecisionControls from './DecisionControls';
import { formatDateTime, formatTarget, labelOf, OWNER_TEAM_LABELS } from '../../api/format';


// ═══════════════════════════════════════════════════════════════════
// 2. Edit form — title and instructions (posts a new version)
// ═══════════════════════════════════════════════════════════════════
// Only the text the receiving team reads is editable. Action, owner, target and
// recheck days come from the agent's catalog choice; changing them is a
// different action, which the analyst does by rejecting.
const EditForm = ({ proposal, onDone }) => {
  const dispatch = useDispatch();
  const write = useSelector((state) => selectProposalWrite(state, proposal.proposal_id));
  const [title, setTitle] = useState(proposal.content.title);
  const [instructions, setInstructions] = useState(proposal.content.instructions);

  const saving = write?.kind === 'edit' && write.status === 'loading';
  const error = write?.kind === 'edit' && write.status === 'failed' ? write.error : null;
  const unchanged = title === proposal.content.title && instructions === proposal.content.instructions;
  const empty = !title.trim() || !instructions.trim();

  const save = async (e) => {
    e.preventDefault();
    const result = await dispatch(editProposal({
      id: proposal.proposal_id,
      content: { ...proposal.content, title: title.trim(), instructions: instructions.trim() },
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
        Title
        <input value={title} onChange={(e) => setTitle(e.target.value)} disabled={saving} maxLength={200} />
      </label>
      <label>
        Instructions
        <textarea rows={4} value={instructions} onChange={(e) => setInstructions(e.target.value)} disabled={saving} />
      </label>
      <div className='decision-buttons'>
        <button type='button' className='button-secondary' onClick={cancel} disabled={saving}>Cancel</button>
        <button type='submit' disabled={saving || unchanged || empty}>
          {saving ? 'Saving…' : `Save as version ${proposal.version + 1}`}
        </button>
      </div>
      {error && <p className='error' role='alert'>{error.message}</p>}
    </form>
  );
};


// ═══════════════════════════════════════════════════════════════════
// 3. What happened after the decision
// ═══════════════════════════════════════════════════════════════════
const DecisionOutcome = ({ proposal, timeZone }) => {
  const by = `${proposal.decided_by} · ${formatDateTime(proposal.decided_at, timeZone)}`;

  if (proposal.status === 'rejected') {
    return (
      <div className='decision-outcome'>
        <p><strong>Rejected</strong> by {by}</p>
        <p className='muted'>Nothing is sent. The case goes to analyst review.</p>
        {proposal.decision_note && <p className='decision-note'>“{proposal.decision_note}”</p>}
      </div>
    );
  }

  const { dispatch: sent } = proposal;
  return (
    <div className='decision-outcome'>
      <p><strong>Approved</strong> by {by}</p>
      {sent && (
        <p className='muted'>
          {sent.status === 'failed' ? 'Send failed' : 'Sent'} to {labelOf(OWNER_TEAM_LABELS, sent.owner_team)} · {sent.dispatch_id}
        </p>
      )}
      {proposal.decision_note && <p className='decision-note'>“{proposal.decision_note}”</p>}
    </div>
  );
};

const STATUS_PILLS = {
  pending: <Pill tone='warn'>Waiting for a decision</Pill>,
  approved: <Pill tone='ok'>Approved</Pill>,
  rejected: <Pill tone='bad'>Rejected</Pill>,
};


// ═══════════════════════════════════════════════════════════════════
// 4. RecommendationReview component
// ═══════════════════════════════════════════════════════════════════
// proposalId: InvestigationResult.proposal_id · timeZone: the store's
const RecommendationReview = ({ proposalId, timeZone }) => {
  const dispatch = useDispatch();
  const proposal = useSelector((state) => selectProposal(state, proposalId));
  const fetchStatus = useSelector((state) => selectProposalFetchStatus(state, proposalId));
  const fetchError = useSelector((state) => selectProposalFetchError(state, proposalId));
  const write = useSelector((state) => selectProposalWrite(state, proposalId));
  const isAnalyst = useSelector(selectIsAnalyst);
  const [editing, setEditing] = useState(false);

  // ── 4a. Load it (fresh each time the box appears) ────────────────
  useEffect(() => {
    if (proposalId) dispatch(fetchProposal(proposalId));
  }, [dispatch, proposalId]);

  // ── 4b. Loading / failed ─────────────────────────────────────────
  if (!proposal) {
    return (
      <div className='recommendation-review'>
        {fetchStatus === 'failed' ? (
          <div className='error' role='alert'>
            <p>{fetchError}</p>
            <button type='button' onClick={() => dispatch(fetchProposal(proposalId))}>Retry</button>
          </div>
        ) : (
          <p className='muted'>Loading the recommended action…</p>
        )}
      </div>
    );
  }

  // ── 4c. The action ───────────────────────────────────────────────
  const { content } = proposal;
  const pending = proposal.status === 'pending';
  const busy = write?.status === 'loading';
  // Someone else decided first: the proposal reloads as decided, say why
  const alreadyDecided = !pending && write?.error?.code === 'ALREADY_DECIDED';

  return (
    <div className='recommendation-review'>
      <div className='recommendation-head'>
        <h3>Recommended action</h3>
        {STATUS_PILLS[proposal.status]}
        <span className='muted'>version {proposal.version}</span>
      </div>

      {editing && pending ? (
        <EditForm proposal={proposal} onDone={() => setEditing(false)} />
      ) : (
        <>
          <p className='recommendation-title'>{content.title}</p>
          <p className='recommendation-instructions'>{content.instructions}</p>
        </>
      )}

      <dl className='recommendation-facts'>
        <div><dt>Goes to</dt><dd>{labelOf(OWNER_TEAM_LABELS, content.owner_team)}</dd></div>
        <div><dt>Orders</dt><dd>{formatTarget(content.target)}</dd></div>
        <div><dt>Recheck</dt><dd>{content.recheck_after_days} days after it is sent</dd></div>
      </dl>
      {content.rationale && <p className='muted'>Why: {content.rationale}</p>}
      <EvidenceLinks label='Evidence' ids={proposal.evidence_ids} />

      {/* ── Decide (pending) or what was decided ── */}
      {pending ? (
        <>
          {isAnalyst && !editing && (
            <button type='button' className='button-secondary recommendation-edit' onClick={() => setEditing(true)} disabled={busy}>
              Edit
            </button>
          )}
          <DecisionControls proposal={proposal} approveLabel='Approve and send' disabled={editing} />
        </>
      ) : (
        <>
          {alreadyDecided && <p className='error' role='alert'>{write.error.message}</p>}
          <DecisionOutcome proposal={proposal} timeZone={timeZone} />
        </>
      )}
    </div>
  );
};


// ═══════════════════════════════════════════════════════════════════
// 5. Export
// ═══════════════════════════════════════════════════════════════════
export default RecommendationReview;

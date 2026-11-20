// [10q] DecisionControls — Reject / Approve for one pending proposal, with an optional note
// Used by RecommendationReview (box 9) and, in D-05, QuestionReview (box 6).
//
//   Note (optional) [______________]
//   [Reject]  [Approve and send]
//   Send failed. The proposal is still pending — approve again.
//
// Sends the version the analyst is looking at (proposal.version). One
// Idempotency-Key per click; the same key only for a retry after no response
// (hooks/useIdempotencyKey.js). Viewers see "Only analysts can decide."


// ═══════════════════════════════════════════════════════════════════
// 1. Imports
// ═══════════════════════════════════════════════════════════════════
import { useState } from 'react';
import { useDispatch, useSelector } from 'react-redux';
import { decideProposal } from '../../store/proposals/proposalsThunks';
import { selectProposalWrite } from '../../store/proposals/proposalsSelectors';
import { selectIsAnalyst } from '../../store/auth/authSelectors';
import useIdempotencyKey from '../../hooks/useIdempotencyKey';


// ═══════════════════════════════════════════════════════════════════
// 2. DecisionControls component
// ═══════════════════════════════════════════════════════════════════
// proposal:      the pending Proposal on screen
// approveLabel:  e.g. "Approve and send"
// afterDecided:  optional, called with the decided Proposal (D-05: resume the run)
// disabled:      e.g. while the proposal is being edited
const DecisionControls = ({ proposal, approveLabel = 'Approve', rejectLabel = 'Reject', afterDecided, disabled = false }) => {
  const dispatch = useDispatch();
  const isAnalyst = useSelector(selectIsAnalyst);
  const write = useSelector((state) => selectProposalWrite(state, proposal.proposal_id));
  const { keyFor, settle } = useIdempotencyKey();
  const [note, setNote] = useState('');

  if (!isAnalyst) {
    return <p className='muted decision-viewer'>Only analysts can decide.</p>;
  }

  const deciding = write?.kind === 'decide' && write.status === 'loading';
  const error = write?.kind === 'decide' && write.status === 'failed' ? write.error : null;

  // ── 2a. One click → one decision request ─────────────────────────
  const decide = async (decision) => {
    const result = await dispatch(decideProposal({
      id: proposal.proposal_id,
      version: proposal.version,
      decision,
      note,
      idempotencyKey: keyFor(decision),
    }));

    if (decideProposal.fulfilled.match(result)) {
      settle(null);
      setNote('');
      afterDecided?.(result.payload);
    } else {
      settle(result.payload); // keeps the key only if there was no response
    }
  };

  // ── 2b. Render ───────────────────────────────────────────────────
  const id = `decision-note-${proposal.proposal_id}`;
  return (
    <div className='decision-controls'>
      <label htmlFor={id}>Note <span className='muted'>(optional)</span></label>
      <textarea
        id={id}
        rows={2}
        value={note}
        onChange={(e) => setNote(e.target.value)}
        disabled={deciding || disabled}
        placeholder='Why you approve or reject — saved with the decision'
      />
      <div className='decision-buttons'>
        <button type='button' className='button-secondary' onClick={() => decide('reject')} disabled={deciding || disabled}>
          {rejectLabel}
        </button>
        <button type='button' onClick={() => decide('approve')} disabled={deciding || disabled}>
          {deciding ? 'Saving…' : approveLabel}
        </button>
      </div>
      {error && (
        <p className='error' role='alert'>
          {error.noResponse
            ? "Couldn't reach the server. Try again — it won't be sent twice."
            : error.message}
        </p>
      )}
    </div>
  );
};


// ═══════════════════════════════════════════════════════════════════
// 3. Export
// ═══════════════════════════════════════════════════════════════════
export default DecisionControls;

// [10t] CloseCaseButton — "Mark as resolved" for a case in analyst review
// The agent's workflow ends in analyst_review when the action was rejected, the
// result was unsure, or the second fix didn't work. Once the analyst has handled
// the problem, this closes the case (POST /domain/cases/{id}/close).
// Shown when getCaseView says showClose; analysts only (viewers get 403).


// ═══════════════════════════════════════════════════════════════════
// 1. Imports
// ═══════════════════════════════════════════════════════════════════
import { useState } from 'react';
import { useDispatch, useSelector } from 'react-redux';
import { closeCase } from '../../store/cases/casesThunks';
import { selectIsAnalyst } from '../../store/auth/authSelectors';
import useIdempotencyKey from '../../hooks/useIdempotencyKey';


// ═══════════════════════════════════════════════════════════════════
// 2. CloseCaseButton component
// ═══════════════════════════════════════════════════════════════════
const CloseCaseButton = ({ caseId }) => {
  const dispatch = useDispatch();
  const isAnalyst = useSelector(selectIsAnalyst);
  const { keyFor, settle } = useIdempotencyKey();
  const [closing, setClosing] = useState(false);
  const [error, setError] = useState(null);

  if (!isAnalyst) return null;

  const close = async () => {
    setClosing(true);
    setError(null);
    const result = await dispatch(closeCase({ caseId, idempotencyKey: keyFor('close') }));
    const failed = !closeCase.fulfilled.match(result);
    settle(failed ? result.payload : null);
    // On success the case reloads as closed and this box goes away
    if (failed) {
      setClosing(false);
      setError(result.payload?.noResponse ? "Couldn't reach the server. Try again." : result.payload?.message);
    }
  };

  return (
    <section className='close-case'>
      <p>
        <strong>Waiting on an analyst.</strong>{' '}
        <span className='muted'>Once the problem is handled, close the case.</span>
      </p>
      <button type='button' onClick={close} disabled={closing}>
        {closing ? 'Closing…' : 'Mark as resolved'}
      </button>
      {error && <p className='error' role='alert'>{error}</p>}
    </section>
  );
};


// ═══════════════════════════════════════════════════════════════════
// 3. Export
// ═══════════════════════════════════════════════════════════════════
export default CloseCaseButton;

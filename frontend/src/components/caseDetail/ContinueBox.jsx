// [10u] ContinueBox — "saved, but the agent hasn't continued yet" → resume only
// Shown when the first call of "decide first, then resume" worked and the second
// didn't (or the page reloaded in between). caseSteps.needsResume decides when.
// Used by QuestionReview (decision saved) and MerchantReplyCard (reply saved).


// ═══════════════════════════════════════════════════════════════════
// 1. Imports
// ═══════════════════════════════════════════════════════════════════
import { useSelector } from 'react-redux';
import { selectIsAnalyst } from '../../store/auth/authSelectors';
import useResume from '../../hooks/useResume';


// ═══════════════════════════════════════════════════════════════════
// 2. ContinueBox component
// ═══════════════════════════════════════════════════════════════════
// saved: what was saved, e.g. "Your decision (rejected)" or "The merchant's reply"
const ContinueBox = ({ investigationId, saved }) => {
  const isAnalyst = useSelector(selectIsAnalyst);
  const { resume, resuming, error } = useResume(investigationId);

  return (
    <div className='continue-box' role='status'>
      <p>{saved} is saved. The agent hasn't continued yet.</p>
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
// 3. Export
// ═══════════════════════════════════════════════════════════════════
export default ContinueBox;

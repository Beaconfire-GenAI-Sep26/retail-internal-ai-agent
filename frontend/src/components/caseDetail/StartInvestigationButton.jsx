// [10k] StartInvestigationButton — box 4: starts the agent (analysts only)
// Label comes from getCaseView (caseSteps.js):
//   "Start investigation" (step 1) · "Start new investigation" (step 7) · "Start again" (failed)
// Viewers see a note instead of the button: the backend answers 403 for them
// anyway, hiding it just keeps them from hitting that error.
//
// D-05 (commit 7) sends reopen_of on "Start new investigation"; commit 9 adds the
// token refresh before Start.


// ═══════════════════════════════════════════════════════════════════
// 1. Imports
// ═══════════════════════════════════════════════════════════════════
import { useDispatch, useSelector } from 'react-redux';
import { startInvestigation } from '../../store/investigations/investigationsThunks';
import { selectIsAnalyst } from '../../store/auth/authSelectors';
import { selectStartStatus, selectStartError } from '../../store/investigations/investigationsSelectors';


// ═══════════════════════════════════════════════════════════════════
// 2. StartInvestigationButton component
// ═══════════════════════════════════════════════════════════════════
const StartInvestigationButton = ({ caseId, label }) => {
  const dispatch = useDispatch();
  const isAnalyst = useSelector(selectIsAnalyst);
  const startStatus = useSelector(selectStartStatus);
  const startError = useSelector(selectStartError);

  if (!isAnalyst) {
    return <p className='muted'>Only LOE analysts can start an investigation.</p>;
  }

  const starting = startStatus === 'loading';

  return (
    <div className='investigation-start'>
      <button type='button' onClick={() => dispatch(startInvestigation(caseId))} disabled={starting}>
        {starting ? 'Starting…' : label}
      </button>
      {startError && <p className='error' role='alert'>{startError}</p>}
    </div>
  );
};


// ═══════════════════════════════════════════════════════════════════
// 3. Export
// ═══════════════════════════════════════════════════════════════════
export default StartInvestigationButton;

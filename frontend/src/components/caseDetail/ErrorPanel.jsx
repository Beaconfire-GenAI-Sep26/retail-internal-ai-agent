// [10p] ErrorPanel — box 10: why the run stopped, and Start again
// The message comes from error.code (ui-workflow.md v0.3 "Error messages").
// error.message is written for developers, so it only shows under "Details".
// Every code allows Start again.


// ═══════════════════════════════════════════════════════════════════
// 1. Imports
// ═══════════════════════════════════════════════════════════════════
import { formatInvestigationError } from '../../api/format';
import StartInvestigationButton from './StartInvestigationButton';


// ═══════════════════════════════════════════════════════════════════
// 2. ErrorPanel component
// ═══════════════════════════════════════════════════════════════════
// investigation: the failed InvestigationView · startLabel: from getCaseView
const ErrorPanel = ({ caseId, investigation, startLabel }) => {
  const { error, investigation_id: id } = investigation;

  return (
    <div className='error-panel' role='alert'>
      <h3>Investigation stopped</h3>
      <p>{formatInvestigationError(error?.code)}</p>
      <details>
        <summary>Details</summary>
        <dl>
          <dt>Investigation</dt>
          <dd>{id}</dd>
          <dt>Code</dt>
          <dd>{error?.code ?? '—'}</dd>
          {error?.message && (
            <>
              <dt>Message</dt>
              <dd>{error.message}</dd>
            </>
          )}
        </dl>
      </details>
      <StartInvestigationButton caseId={caseId} label={startLabel} />
    </div>
  );
};


// ═══════════════════════════════════════════════════════════════════
// 3. Export
// ═══════════════════════════════════════════════════════════════════
export default ErrorPanel;

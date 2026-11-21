// [10w] PreviousInvestigation — box 15: the first run, folded, above the second
// A case gets a second investigation only when the first fix didn't work
// (recheck not improved → reopened → "Start new investigation" with reopen_of).
// The first run stays visible for the whole second run (getCaseView.showPrevious).
//
//   ▸ First investigation · Packing → Add a bag check for large orders → Recheck [Not improved] 26 / 193 (13.5%)
//     (open) the full result, the action that was sent, and the recheck numbers
//
// Data: Agent GET /investigations/{reopen_of}; its action and recheck come from
// CaseDetail (proposals, rechecks), matched by the first run's proposal_id.


// ═══════════════════════════════════════════════════════════════════
// 1. Imports
// ═══════════════════════════════════════════════════════════════════
import { useEffect } from 'react';
import { useDispatch, useSelector } from 'react-redux';
import { fetchPreviousInvestigation } from '../../store/investigations/investigationsThunks';
import { selectPrevious } from '../../store/investigations/investigationsSelectors';
import { selectCaseDetail } from '../../store/cases/casesSelectors';
import { findRecheck } from './caseSteps';
import ResultPanel from './ResultPanel';
import { RecheckFacts, RecheckPill } from './RecheckPanel';
import { formatRateWindow, labelOf, CAUSE_LABELS, OWNER_TEAM_LABELS } from '../../api/format';


// ═══════════════════════════════════════════════════════════════════
// 2. PreviousInvestigation component
// ═══════════════════════════════════════════════════════════════════
// investigation: the current (second) run — its reopen_of names the first
const PreviousInvestigation = ({ investigation }) => {
  const dispatch = useDispatch();
  const previousId = investigation.reopen_of;
  const previous = useSelector(selectPrevious);
  const caseDetail = useSelector((state) => selectCaseDetail(state, investigation.case_id));

  useEffect(() => {
    if (previousId) dispatch(fetchPreviousInvestigation(previousId));
  }, [dispatch, previousId]);

  // ── 2a. Loading / failed ─────────────────────────────────────────
  const view = previous.id === previousId ? previous.view : null;
  if (!view) {
    return (
      <div className='previous-investigation'>
        {previous.status === 'failed' ? (
          <p className='error'>
            {previous.error}{' '}
            <button type='button' className='button-secondary' onClick={() => dispatch(fetchPreviousInvestigation(previousId))}>
              Retry
            </button>
          </p>
        ) : (
          <p className='muted'>Loading the first investigation ({previousId})…</p>
        )}
      </div>
    );
  }

  // ── 2b. Its cause, action and recheck ────────────────────────────
  const { result } = view;
  const action = caseDetail?.proposals?.find((p) => p.proposal_id === result?.proposal_id) ?? null;
  const recheck = findRecheck(view, caseDetail);
  const cause = result?.cause_category ? labelOf(CAUSE_LABELS, result.cause_category) : 'No cause confirmed';

  return (
    <details className='previous-investigation'>
      <summary>
        <span className='muted'>First investigation ·</span> <strong>{cause}</strong>
        {action && <> → {action.content.title}</>}
        {recheck && (
          <>
            {' '}→ Recheck <RecheckPill status={recheck.status} />
            {recheck.after && <span className='muted'> {formatRateWindow(recheck.after)}</span>}
          </>
        )}
      </summary>

      <div className='previous-body'>
        <p className='muted'>{view.investigation_id} · started by {view.started_by}</p>
        {result && <ResultPanel result={result} checks={view.checks} hypotheses={view.hypotheses} />}
        {action && (
          <div className='previous-action'>
            <h4>Action sent</h4>
            <p><strong>{action.content.title}</strong> · {labelOf(OWNER_TEAM_LABELS, action.content.owner_team)}</p>
            <p className='muted'>{action.content.instructions}</p>
          </div>
        )}
        {recheck && (
          <div className='previous-action'>
            <h4>Recheck</h4>
            <RecheckFacts recheck={recheck} />
          </div>
        )}
      </div>
    </details>
  );
};


// ═══════════════════════════════════════════════════════════════════
// 3. Export
// ═══════════════════════════════════════════════════════════════════
export default PreviousInvestigation;

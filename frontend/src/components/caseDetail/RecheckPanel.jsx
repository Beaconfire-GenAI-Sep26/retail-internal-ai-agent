// [10s] RecheckPanel — box 13: did the fix work?
// Domain schedules a recheck when an action is approved (dispatched_at +
// recheck_after_days). On that day it compares the target orders' rate after
// the fix with before, and with the store's other orders over the same days.
//
//   ④ DID THE FIX WORK? ──────────────────────── RCK-…     ← Chapter
//   [Not improved]  Checked Dec 1, 2026
//   Orders          dinner · 5+ items
//   Before the fix  29 / 204 (14.2%) · Nov 3 – Nov 15, 2026
//   After the fix   26 / 193 (13.5%) · Nov 16 – Nov 30, 2026
//   Other orders    17 / 1062 (1.6%) · same days
//   The fix didn't work. Start a new investigation above.      ← next step
//
// Scheduled: the analyst can run it now for the demo ("Run recheck now (demo)").
// Shown at steps 6 and 7 and the ends after them (getCaseView.showRecheck).
// InvestigationPanel places it right after the action it rechecks (D-06).


// ═══════════════════════════════════════════════════════════════════
// 1. Imports
// ═══════════════════════════════════════════════════════════════════
import { useState } from 'react';
import { useDispatch, useSelector } from 'react-redux';
import { selectInvestigation } from '../../store/investigations/investigationsSelectors';
import { selectCaseDetail } from '../../store/cases/casesSelectors';
import { selectIsAnalyst } from '../../store/auth/authSelectors';
import { runRecheck } from '../../store/rechecks/rechecksThunks';
import { selectRecheckRun } from '../../store/rechecks/rechecksSelectors';
import useIdempotencyKey from '../../hooks/useIdempotencyKey';
import { USE_MOCKS } from '../../api/mockAuth';
import { setNextRecheck } from '../../api/mocks/mockInvestigations';
import { getCaseView, findRecheck } from './caseSteps';
import Pill from '../common/Pill';
import Chapter from '../common/Chapter';
import {
  formatDate,
  formatDayRange,
  formatRateWindow,
  formatTarget,
  labelOf,
  RECHECK_STATUS_LABELS,
} from '../../api/format';


// ═══════════════════════════════════════════════════════════════════
// 2. Pieces (RecheckFacts is reused by PreviousInvestigation)
// ═══════════════════════════════════════════════════════════════════
const STATUS_TONES = { scheduled: 'accent', improved: 'ok', not_improved: 'bad', insufficient_data: 'warn' };

export const RecheckPill = ({ status }) => (
  <Pill tone={STATUS_TONES[status] ?? 'neutral'}>{labelOf(RECHECK_STATUS_LABELS, status)}</Pill>
);

// One RateWindow as "29 / 204 (14.2%) · Nov 3 – Nov 15, 2026"
const RateRow = ({ label, window: w }) => (
  <div>
    <dt>{label}</dt>
    <dd>
      {formatRateWindow(w)} <span className='muted'>· {formatDayRange(w.start, w.end)}</span>
    </dd>
  </div>
);

export const RecheckFacts = ({ recheck }) => (
  <dl className='recheck-facts'>
    <div><dt>Orders</dt><dd>{formatTarget(recheck.target)}</dd></div>
    <RateRow label='Before the fix' window={recheck.before} />
    {recheck.after && <RateRow label='After the fix' window={recheck.after} />}
    {recheck.control && <RateRow label='Other orders' window={recheck.control} />}
  </dl>
);

// What happens next, from the result and where Domain moved the case
const nextStep = (recheck, caseStatus) => {
  switch (recheck.status) {
    case 'improved':
      return 'The fix worked. The case is closed.';
    case 'insufficient_data':
      return 'Too few orders to tell whether the fix worked. The case is paused.';
    case 'not_improved':
      return caseStatus === 'reopened'
        ? "The fix didn't work. Start a new investigation above."
        : "The second fix didn't work either. The case goes to analyst review.";
    default:
      return null;
  }
};


// ═══════════════════════════════════════════════════════════════════
// 3. Run it now (demo) — analysts only, while scheduled
// ═══════════════════════════════════════════════════════════════════
// In mock mode a select picks the result, instead of __mocks.nextRecheck() in the console.
const DEMO_RESULTS = [
  ['', 'Scenario default'],
  ['improved', 'Improved'],
  ['not_improved', 'Not improved'],
  ['insufficient_data', 'Not enough data'],
];

const RunRecheck = ({ recheck, caseId }) => {
  const dispatch = useDispatch();
  const run = useSelector((state) => selectRecheckRun(state, recheck.recheck_id));
  const { keyFor, settle } = useIdempotencyKey();
  const [demoResult, setDemoResult] = useState('');
  const running = run?.status === 'loading';

  const start = async () => {
    if (USE_MOCKS && demoResult) setNextRecheck(demoResult);
    const result = await dispatch(runRecheck({ id: recheck.recheck_id, caseId, idempotencyKey: keyFor('run') }));
    settle(runRecheck.fulfilled.match(result) ? null : result.payload);
  };

  // No recheck route on the real backend until C-04: mock mode only
  if (!USE_MOCKS) return null;

  return (
    <div className='recheck-run'>
      {USE_MOCKS && (
        <label>
          <span className='muted'>Mock result</span>
          <select value={demoResult} onChange={(e) => setDemoResult(e.target.value)} disabled={running}>
            {DEMO_RESULTS.map(([value, text]) => <option key={value} value={value}>{text}</option>)}
          </select>
        </label>
      )}
      <button type='button' onClick={start} disabled={running}>
        {running ? 'Running…' : 'Run recheck now (demo)'}
      </button>
      {run?.status === 'failed' && (
        <p className='error' role='alert'>
          {run.error.noResponse ? "Couldn't reach the server. Try again." : run.error.message}
        </p>
      )}
    </div>
  );
};


// ═══════════════════════════════════════════════════════════════════
// 4. RecheckPanel component
// ═══════════════════════════════════════════════════════════════════
const RecheckPanel = ({ caseId }) => {
  const investigation = useSelector((state) => selectInvestigation(state, caseId));
  const caseDetail = useSelector((state) => selectCaseDetail(state, caseId));
  const isAnalyst = useSelector(selectIsAnalyst);

  const view = getCaseView({ investigation, caseDetail });
  const recheck = view.showRecheck ? findRecheck(investigation, caseDetail) : null;
  if (!recheck) return null;

  const timeZone = caseDetail.store?.timezone;
  const scheduled = recheck.status === 'scheduled';
  const next = nextStep(recheck, caseDetail.status);

  return (
    <>
    <Chapter title='Did the fix work?' meta={<span className='mono'>{recheck.recheck_id}</span>} />
    <section className={`recheck-panel recheck-${recheck.status}`}>
      <div className='recheck-head'>
        <RecheckPill status={recheck.status} />
        {recheck.data_sufficient === false && <Pill tone='warn'>Not enough orders</Pill>}
        <span className='muted'>
          {scheduled
            ? <>Recheck on {formatDate(recheck.scheduled_for, timeZone)}</>
            : <>Checked {formatDate(recheck.ran_at ?? recheck.scheduled_for, timeZone)}</>}
        </span>
      </div>

      <RecheckFacts recheck={recheck} />

      {scheduled && (
        <p className='muted'>
          On that day the rate for these orders after the fix is compared with before, and with the
          store's other orders over the same days.
        </p>
      )}
      {next && <p className={`recheck-next recheck-next-${recheck.status}`}>{next}</p>}

      {scheduled && isAnalyst && <RunRecheck recheck={recheck} caseId={caseId} />}
    </section>
    </>
  );
};


// ═══════════════════════════════════════════════════════════════════
// 5. Export
// ═══════════════════════════════════════════════════════════════════
export default RecheckPanel;

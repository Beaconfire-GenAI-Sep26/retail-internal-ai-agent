// [10s] RecheckPanel — box 13: did the fix work?
// Domain schedules a recheck when an action is approved (dispatched_at +
// recheck_after_days). On that day it compares the target orders' rate after
// the fix with before, and with the store's other orders over the same days.
//
//   Did the fix work?                                   [Scheduled]
//   Recheck on Nov 30, 2026
//   Orders          dinner · 5+ items
//   Before the fix  29 / 204 (14.2%) · Nov 3 – Nov 15, 2026
//
// Shown at steps 6 and 7 and the ends after them (getCaseView.showRecheck).
// Sits under InvestigationPanel, outside it (page map). Commit 7 adds the
// "Run recheck now (demo)" button and what to do next for each result.


// ═══════════════════════════════════════════════════════════════════
// 1. Imports
// ═══════════════════════════════════════════════════════════════════
import { useSelector } from 'react-redux';
import { selectInvestigation } from '../../store/investigations/investigationsSelectors';
import { selectCaseDetail } from '../../store/cases/casesSelectors';
import { getCaseView, findRecheck } from './caseSteps';
import Pill from '../common/Pill';
import {
  formatDate,
  formatDayRange,
  formatRateWindow,
  formatTarget,
  labelOf,
  RECHECK_STATUS_LABELS,
} from '../../api/format';


// ═══════════════════════════════════════════════════════════════════
// 2. Helpers
// ═══════════════════════════════════════════════════════════════════
const STATUS_TONES = { scheduled: 'accent', improved: 'ok', not_improved: 'bad', insufficient_data: 'warn' };

// One RateWindow as "29 / 204 (14.2%) · Nov 3 – Nov 15, 2026"
const RateRow = ({ label, window: w }) => (
  <div>
    <dt>{label}</dt>
    <dd>
      {formatRateWindow(w)} <span className='muted'>· {formatDayRange(w.start, w.end)}</span>
    </dd>
  </div>
);


// ═══════════════════════════════════════════════════════════════════
// 3. RecheckPanel component
// ═══════════════════════════════════════════════════════════════════
const RecheckPanel = ({ caseId }) => {
  const investigation = useSelector((state) => selectInvestigation(state, caseId));
  const caseDetail = useSelector((state) => selectCaseDetail(state, caseId));

  const view = getCaseView({ investigation, caseDetail });
  const recheck = view.showRecheck ? findRecheck(investigation, caseDetail) : null;
  if (!recheck) return null;

  const timeZone = caseDetail.store?.timezone;
  const scheduled = recheck.status === 'scheduled';

  return (
    <section className='recheck-panel'>
      <div className='recheck-head'>
        <h2>Did the fix work?</h2>
        <Pill tone={STATUS_TONES[recheck.status] ?? 'neutral'}>{labelOf(RECHECK_STATUS_LABELS, recheck.status)}</Pill>
      </div>

      <p className='muted'>
        {scheduled
          ? <>Recheck on {formatDate(recheck.scheduled_for, timeZone)}</>
          : <>Checked {formatDate(recheck.ran_at ?? recheck.scheduled_for, timeZone)}</>}
      </p>

      <dl className='recheck-facts'>
        <div><dt>Orders</dt><dd>{formatTarget(recheck.target)}</dd></div>
        <RateRow label='Before the fix' window={recheck.before} />
        {recheck.after && <RateRow label='After the fix' window={recheck.after} />}
        {recheck.control && <RateRow label='Other orders' window={recheck.control} />}
      </dl>

      {scheduled && (
        <p className='muted'>
          On that day the rate for these orders after the fix is compared with before, and with the
          store's other orders over the same days.
        </p>
      )}
    </section>
  );
};


// ═══════════════════════════════════════════════════════════════════
// 4. Export
// ═══════════════════════════════════════════════════════════════════
export default RecheckPanel;

// [10f] CaseHeader — top of the case page: which case, which store, why it opened
//   CASE-0001  [● Awaiting decision]
//   Golden Wok Kitchen                                          ← h1
//   ⌂ STORE-A   ⌖ Chicago   △ Trigger Over goal   ▦ Window Nov 9 – Nov 15, 2026
// The three numbers (rate, baseline, goal) are in CaseKpis, chapter 1.


// ═══════════════════════════════════════════════════════════════════
// 1. Imports + icons
// ═══════════════════════════════════════════════════════════════════
import StatusBadge from '../StatusBadge';
import {
  formatDateRange,
  formatInvestigationError,
  TRIGGER_LABELS,
} from '../../api/format';

// Line icons in front of each fact (decorative — the label names the fact)
const ICONS = {
  store: 'M3 9l1-5h16l1 5M4 9v11h16V9M9 20v-6h6v6',
  city: 'M12 21s-7-6.2-7-12a7 7 0 0 1 14 0c0 5.8-7 12-7 12zM12 6.5a2.5 2.5 0 1 0 0 5 2.5 2.5 0 0 0 0-5z',
  trigger: 'M12 3l9 16H3zM12 10v4',
  window: 'M5 5h14a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V7a2 2 0 0 1 2-2zM3 10h18M8 3v4M16 3v4',
};
const Icon = ({ d }) => (
  <svg viewBox='0 0 24 24' aria-hidden='true' fill='none' stroke='currentColor' strokeWidth='2'
    strokeLinecap='round' strokeLinejoin='round'>
    <path d={d} />
  </svg>
);

// One fact: icon · label · value. Store and city are obvious from the value, so
// their label is for screen readers only (sr-only).
const Fact = ({ icon, label, showLabel = true, children }) => (
  <div>
    <dt><Icon d={ICONS[icon]} /><span className={showLabel ? undefined : 'sr-only'}>{label}</span></dt>
    <dd>{children}</dd>
  </div>
);


// ═══════════════════════════════════════════════════════════════════
// 2. CaseHeader component
// ═══════════════════════════════════════════════════════════════════
// caseDetail: contract CaseDetail (GET /domain/cases/{case_id})
const CaseHeader = ({ caseDetail }) => {
  const { store } = caseDetail;

  return (
    <header className='case-header'>
      <div className='case-id-row'>
        <span className='mono'>{caseDetail.case_id}</span>
        <StatusBadge status={caseDetail.status} />
      </div>
      <h1>{caseDetail.store_name}</h1>

      <dl className='case-facts'>
        <Fact icon='store' label='Store' showLabel={false}>{store.store_id}</Fact>
        <Fact icon='city' label='City' showLabel={false}>{store.city}</Fact>
        <Fact icon='trigger' label='Trigger'>
          {TRIGGER_LABELS[caseDetail.trigger_rule] ?? caseDetail.trigger_rule}
        </Fact>
        {/* The 7 days that triggered the case, in the store's timezone */}
        <Fact icon='window' label='Window'>
          {formatDateRange(caseDetail.window_start, caseDetail.window_end, store.timezone)}
        </Fact>
      </dl>

      {/* Set by the Domain Service when the last investigation failed. It holds the
          investigation error code, so it gets the same friendly text as ErrorPanel. */}
      {caseDetail.last_error && (
        <p className='error' title={caseDetail.last_error}>
          Last investigation failed: {formatInvestigationError(caseDetail.last_error)}
        </p>
      )}
    </header>
  );
};


// ═══════════════════════════════════════════════════════════════════
// 3. Export
// ═══════════════════════════════════════════════════════════════════
export default CaseHeader;

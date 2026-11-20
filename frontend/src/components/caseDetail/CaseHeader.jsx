// [10f] CaseHeader — top of the case page: which store, how bad, compared to what
//   title row:  CASE-0001 · Golden Wok Kitchen  [Open]
//   facts row:  Store STORE-A | City Chicago | Trigger Over goal | Trigger window Nov 9 – Nov 15, 2026
//   3 cards:    M&I rate (this week) · Baseline · Goal


// ═══════════════════════════════════════════════════════════════════
// 1. Imports
// ═══════════════════════════════════════════════════════════════════
import StatusBadge from '../StatusBadge';
import {
  formatRate,
  formatRatio,
  formatDateRange,
  TRIGGER_LABELS,
} from '../../api/format';


// ═══════════════════════════════════════════════════════════════════
// 2. CaseHeader component
// ═══════════════════════════════════════════════════════════════════
// caseDetail: contract CaseDetail (GET /domain/cases/{case_id})
const CaseHeader = ({ caseDetail }) => {
  const { store } = caseDetail;

  return (
    <header className='case-header'>
      {/* ── Title row ── */}
      <div className='case-title'>
        <h1>{caseDetail.case_id} · {caseDetail.store_name}</h1>
        <StatusBadge status={caseDetail.status} />
      </div>

      {/* ── Case facts — small label above each value ── */}
      <dl className='case-facts'>
        <div>
          <dt>Store</dt>
          <dd>{store.store_id}</dd>
        </div>
        <div>
          <dt>City</dt>
          <dd>{store.city}</dd>
        </div>
        <div>
          <dt>Trigger</dt>
          <dd>{TRIGGER_LABELS[caseDetail.trigger_rule] ?? caseDetail.trigger_rule}</dd>
        </div>
        <div>
          {/* The 7 days that triggered the case, in the store's timezone */}
          <dt>Trigger window</dt>
          <dd>{formatDateRange(caseDetail.window_start, caseDetail.window_end, store.timezone)}</dd>
        </div>
      </dl>

      {/* Set by the Domain Service when the last investigation failed */}
      {caseDetail.last_error && <p className='error'>Last investigation failed: {caseDetail.last_error}</p>}

      {/* ── Stat cards ── */}
      <div className='stat-cards'>
        <div className='stat-card stat-card-alert'>
          <span className='stat-label'>M&amp;I rate (trigger window)</span>
          <strong className='stat-value'>{formatRate(caseDetail.mi_rate)}</strong>
          <span className='muted'>
            {formatRatio(caseDetail.attributable_claims, caseDetail.eligible_orders)} claims / orders
          </span>
        </div>
        <div className='stat-card'>
          <span className='stat-label'>Baseline</span>
          <strong className='stat-value'>{formatRate(caseDetail.baseline_rate)}</strong>
          <span className='muted'>the store's usual level, prior 28 days</span>
        </div>
        <div className='stat-card'>
          <span className='stat-label'>Goal</span>
          <strong className='stat-value'>{formatRate(caseDetail.goal_rate)}</strong>
          <span className='muted'>above this opens a case</span>
        </div>
      </div>
    </header>
  );
};


// ═══════════════════════════════════════════════════════════════════
// 3. Export
// ═══════════════════════════════════════════════════════════════════
export default CaseHeader;

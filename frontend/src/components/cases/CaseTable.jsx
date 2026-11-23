// [10e] CaseTable — the case queue: one row per CaseSummary
// Clicking anywhere on a row opens /cases/:caseId. The case ID is also a real
// link, so keyboard users and "open in new tab" still work.


// ═══════════════════════════════════════════════════════════════════
// 1. Imports
// ═══════════════════════════════════════════════════════════════════
import { Link, useNavigate } from 'react-router';
import StatusBadge from '../StatusBadge';
import { formatRate, formatRatio, TRIGGER_LABELS } from '../../api/format';


// ═══════════════════════════════════════════════════════════════════
// 2. CaseTable component
// ═══════════════════════════════════════════════════════════════════
// cases: contract CaseSummary[] — never empty here; the page shows the empty state
//
// No "Window" column: CaseSummary has no store timezone, and the window dates
// are only correct in the store's timezone. The case header shows them.
const CaseTable = ({ cases }) => {
  const navigate = useNavigate();

  return (
    <div className='table-scroll'>
      <table className='case-table'>
        <thead>
          <tr>
            <th>Case</th>
            <th>Store</th>
            <th>M&amp;I rate</th>
            <th>Baseline</th>
            <th>Goal</th>
            <th>Trigger</th>
            <th>Status</th>
          </tr>
        </thead>
        <tbody>
          {cases.map((c) => (
            // The whole row opens the case; a click on the case link is left to the
            // link (else it navigates twice — Back needs two presses — and ⌘-click
            // opens a new tab AND moves this one)
            <tr key={c.case_id} onClick={(e) => { if (!e.target.closest('a')) navigate(`/cases/${c.case_id}`); }}>
              <td>
                <Link to={`/cases/${c.case_id}`}>{c.case_id}</Link>
              </td>
              <td>
                {c.store_name} <span className='muted'>{c.store_id}</span>
              </td>
              {/* Rates always show their sample size (ui-workflow.md display rules) */}
              <td>
                <strong>{formatRate(c.mi_rate)}</strong>{' '}
                <span className='muted'>{formatRatio(c.attributable_claims, c.eligible_orders)}</span>
              </td>
              <td>{formatRate(c.baseline_rate)}</td>
              <td>{formatRate(c.goal_rate)}</td>
              <td>{TRIGGER_LABELS[c.trigger_rule] ?? c.trigger_rule}</td>
              <td><StatusBadge status={c.status} /></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
};


// ═══════════════════════════════════════════════════════════════════
// 3. Export
// ═══════════════════════════════════════════════════════════════════
export default CaseTable;

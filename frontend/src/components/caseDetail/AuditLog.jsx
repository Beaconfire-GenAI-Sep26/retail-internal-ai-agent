// [10x] AuditLog — box 16: who did what to the case, and when
// A sidebar on wide screens, under the page on narrow ones (CaseDetail layout).
//
//   Activity
//   Nov 16, 9:12 AM  USR-001   Proposal approved   PROP-0001 v2
//   Nov 16, 9:10 AM  Agent     Proposal created    PROP-0001 v1
//   …
//   [Show all 12]
//
// Newest first. The request ID (for tracing a call in the logs) is in each row's
// tooltip. Reloaded whenever the case, the run's status or a proposal changes —
// every action that writes an audit row changes one of those.


// ═══════════════════════════════════════════════════════════════════
// 1. Imports
// ═══════════════════════════════════════════════════════════════════
import { useEffect, useMemo, useState } from 'react';
import { useDispatch, useSelector } from 'react-redux';
import { fetchAudit } from '../../store/audit/auditThunks';
import { newestFirst, selectAuditEntries, selectAuditStatus, selectAuditError } from '../../store/audit/auditSelectors';
import { selectCaseDetail } from '../../store/cases/casesSelectors';
import { selectInvestigation } from '../../store/investigations/investigationsSelectors';
import { formatDateTime, formatDateTimeShort, labelOf, AUDIT_ACTION_LABELS } from '../../api/format';


// ═══════════════════════════════════════════════════════════════════
// 2. Helpers
// ═══════════════════════════════════════════════════════════════════
const SHOWN_AT_FIRST = 7;

// AuditEntry.actor_id → who, in words. Services get a name; people keep their ID.
const SERVICE_NAMES = { svc_agent: 'Agent', svc_monitor: 'Monitor' };
const actorName = (entry) => SERVICE_NAMES[entry.actor_id] ?? entry.actor_id;


// ═══════════════════════════════════════════════════════════════════
// 3. AuditLog component
// ═══════════════════════════════════════════════════════════════════
const AuditLog = ({ caseId, timeZone }) => {
  const dispatch = useDispatch();
  const raw = useSelector((state) => selectAuditEntries(state, caseId));
  const status = useSelector(selectAuditStatus);
  const error = useSelector(selectAuditError);
  const caseDetail = useSelector((state) => selectCaseDetail(state, caseId));
  const runStatus = useSelector((state) => selectInvestigation(state, caseId)?.status);
  const proposalsById = useSelector((state) => state.proposals.byId);
  const [showAll, setShowAll] = useState(false);

  // ── 3a. Reload with the case ─────────────────────────────────────
  useEffect(() => {
    dispatch(fetchAudit(caseId));
  }, [dispatch, caseId, caseDetail, runStatus, proposalsById]);

  const entries = useMemo(() => newestFirst(raw), [raw]);
  const shown = showAll ? entries : entries.slice(0, SHOWN_AT_FIRST);

  // ── 3b. Render ───────────────────────────────────────────────────
  return (
    <aside className='audit-log' aria-labelledby='audit-log-title'>
      <h2 id='audit-log-title'>Activity</h2>

      {status === 'failed' && entries.length === 0 && (
        <p className='error'>
          {error}{' '}
          <button type='button' className='button-secondary' onClick={() => dispatch(fetchAudit(caseId))}>Retry</button>
        </p>
      )}
      {status === 'loading' && entries.length === 0 && <p className='muted'>Loading…</p>}
      {status === 'succeeded' && entries.length === 0 && <p className='muted'>Nothing yet.</p>}

      {entries.length > 0 && (
        <ol>
          {shown.map((e) => (
            <li key={e.audit_id} title={`${formatDateTime(e.at, timeZone)} · request ${e.request_id}`}>
              <span className='audit-time'>{formatDateTimeShort(e.at, timeZone)}</span>
              <span className='audit-what'>{labelOf(AUDIT_ACTION_LABELS, e.action)}</span>
              <span className='audit-who'>
                {actorName(e)}
                {e.proposal_id && <> · {e.proposal_id}{e.version != null && ` v${e.version}`}</>}
              </span>
            </li>
          ))}
        </ol>
      )}

      {entries.length > SHOWN_AT_FIRST && (
        <button type='button' className='button-secondary audit-more' onClick={() => setShowAll(!showAll)}>
          {showAll ? 'Show fewer' : `Show all ${entries.length}`}
        </button>
      )}
    </aside>
  );
};


// ═══════════════════════════════════════════════════════════════════
// 4. Export
// ═══════════════════════════════════════════════════════════════════
export default AuditLog;

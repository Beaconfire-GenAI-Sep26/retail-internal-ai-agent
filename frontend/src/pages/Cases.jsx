// [12a] Cases page — /cases — any logged-in user
// D-02: store-scoped case queue from the Domain API (M&I rate, baseline, goal, status)
// Four states the analyst can tell apart: loading · error · no cases · the table


// ═══════════════════════════════════════════════════════════════════
// 1. Imports
// ═══════════════════════════════════════════════════════════════════
import { useEffect, useState } from 'react';
import { useDispatch, useSelector } from 'react-redux';
import { fetchCases } from '../store/cases/casesThunks';
import { selectIsAnalyst, selectStoreIds } from '../store/auth/authSelectors';
import {
  selectCaseList,
  selectCaseListStatus,
  selectCaseListError,
} from '../store/cases/casesSelectors';
import CaseFilters from '../components/cases/CaseFilters';
import CaseTable from '../components/cases/CaseTable';
import MonitorRun from '../components/cases/MonitorRun';

// Stable fallback, so useSelector doesn't return a new [] on every render
const NO_STORES = [];


// ═══════════════════════════════════════════════════════════════════
// 2. Cases component
// ═══════════════════════════════════════════════════════════════════
const Cases = () => {
  // ── 2a. Filter state (local — only this page cares) ─────────────
  // '' = all. Each change reloads the list from the backend.
  const [filters, setFilters] = useState({ store_id: '', status: '' });

  // ── 2b. Hooks + case state from Redux ───────────────────────────
  const dispatch = useDispatch();
  const storeIds = useSelector(selectStoreIds) ?? NO_STORES;
  const isAnalyst = useSelector(selectIsAnalyst);
  const cases = useSelector(selectCaseList);
  const status = useSelector(selectCaseListStatus);
  const error = useSelector(selectCaseListError);

  // ── 2c. Load on open and whenever a filter changes ──────────────
  useEffect(() => {
    dispatch(fetchCases(filters));
  }, [dispatch, filters]);

  // ── 2d. Render ──────────────────────────────────────────────────
  const hasFilter = Boolean(filters.store_id || filters.status);

  // Exactly one of these shows below the filters
  let body;
  if (status === 'loading' || status === 'idle') {
    body = <p>Loading cases…</p>;
  } else if (status === 'failed') {
    body = (
      <div className='error' role='alert'>
        <p>{error}</p>
        <button type='button' onClick={() => dispatch(fetchCases(filters))}>Retry</button>
      </div>
    );
  } else if (cases.length === 0) {
    body = (
      <p className='muted'>
        {hasFilter ? 'No cases match these filters.' : 'No cases for your stores right now.'}
        {/* The seed has no cases; the monitor opens them */}
        {!hasFilter && isAnalyst && ' Run the monitor to check your stores.'}
      </p>
    );
  } else {
    body = <CaseTable cases={cases} />;
  }

  return (
    <section>
      {/* Run monitor sits by the title, not in the table: with no cases there is no table */}
      <div className='page-header'>
        <h1>Cases</h1>
        {isAnalyst && <MonitorRun onDone={() => dispatch(fetchCases(filters))} />}
      </div>
      <CaseFilters storeIds={storeIds} filters={filters} onChange={setFilters} />
      {body}
    </section>
  );
};


// ═══════════════════════════════════════════════════════════════════
// 3. Export
// ═══════════════════════════════════════════════════════════════════
export default Cases;

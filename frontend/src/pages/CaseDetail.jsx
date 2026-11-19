// [12b] Case detail page — /cases/:caseId — any logged-in user
// D-02: header (rate vs baseline and goal) · daily history · start + track the investigation
// D-03 adds the diagnosis and approve/reject inside InvestigationPanel.
// caseId is a string like "CASE-0001" (C-01 convention) — never parse it as a number


// ═══════════════════════════════════════════════════════════════════
// 1. Imports
// ═══════════════════════════════════════════════════════════════════
import { useEffect } from 'react';
import { Link, useParams } from 'react-router';
import { useDispatch, useSelector } from 'react-redux';
import { fetchCase } from '../store/cases/casesThunks';
import { fetchLatestInvestigation } from '../store/investigations/investigationsThunks';
import {
  selectCaseDetail,
  selectCaseDetailStatus,
  selectCaseDetailError,
  selectCaseDetailNotFound,
} from '../store/cases/casesSelectors';
import { toStoreDate } from '../api/format';
import CaseHeader from '../components/caseDetail/CaseHeader';
import DailyRateChart from '../components/caseDetail/DailyRateChart';
import InvestigationPanel from '../components/caseDetail/InvestigationPanel';


// ═══════════════════════════════════════════════════════════════════
// 2. CaseDetail component
// ═══════════════════════════════════════════════════════════════════
const CaseDetail = () => {
  // ── 2a. Hooks + case state from Redux ───────────────────────────
  // Matches the :caseId segment in App.jsx → e.g. "CASE-0001"
  const { caseId } = useParams();
  const dispatch = useDispatch();
  const caseDetail = useSelector((state) => selectCaseDetail(state, caseId));
  const status = useSelector(selectCaseDetailStatus);
  const error = useSelector(selectCaseDetailError);
  const notFound = useSelector(selectCaseDetailNotFound);

  // ── 2b. Load the case and its latest investigation ──────────────
  // Two services, two independent calls: if the Agent is down, the case still shows.
  useEffect(() => {
    dispatch(fetchCase(caseId));
    dispatch(fetchLatestInvestigation(caseId));
  }, [dispatch, caseId]);

  // ── 2c. Render ──────────────────────────────────────────────────
  const backLink = <Link to='/cases'>← Back to cases</Link>;

  // Step 1: 404 / 403 — doesn't exist, or another store's case. No Retry: it won't change.
  if (notFound) {
    return (
      <section>
        {backLink}
        <h1>Case {caseId} not found</h1>
        <p>{error}</p>
      </section>
    );
  }

  // Step 2: any other error (network, 5xx) — Retry may help
  if (status === 'failed') {
    return (
      <section>
        {backLink}
        <div className='error' role='alert'>
          <p>{error}</p>
          <button type='button' onClick={() => dispatch(fetchCase(caseId))}>Retry</button>
        </div>
      </section>
    );
  }

  // Step 3: still loading
  if (!caseDetail) {
    return (
      <section>
        {backLink}
        <p>Loading case…</p>
      </section>
    );
  }

  // Step 4: the case
  return (
    <section className='case-detail'>
      {backLink}
      <CaseHeader caseDetail={caseDetail} />
      <DailyRateChart
        dailyRates={caseDetail.daily_rates}
        windowStartDate={toStoreDate(caseDetail.window_start, caseDetail.store.timezone)}
        goalRate={caseDetail.goal_rate}
      />
      <InvestigationPanel caseId={caseId} />
    </section>
  );
};


// ═══════════════════════════════════════════════════════════════════
// 3. Export
// ═══════════════════════════════════════════════════════════════════
export default CaseDetail;

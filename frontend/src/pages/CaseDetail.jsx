// [12b] Case detail page — /cases/:caseId — any logged-in user
// D-01: placeholder that shows the caseId from useParams()
// D-02: baseline, history, evidence · D-03: diagnosis + approve/reject (analysts only)
// caseId is a string like "CASE-0001" (C-01 convention) — never parse it as a number


// ═══════════════════════════════════════════════════════════════════
// 1. Imports
// ═══════════════════════════════════════════════════════════════════
import { Link, useParams } from 'react-router';


// ═══════════════════════════════════════════════════════════════════
// 2. CaseDetail component
// ═══════════════════════════════════════════════════════════════════
const CaseDetail = () => {
  // Matches the :caseId segment in App.jsx → e.g. "CASE-0001"
  const { caseId } = useParams();

  return (
    <section>
      <Link to='/cases'>← Back to cases</Link>
      <h1>{caseId}</h1>
      <p>Case evidence and investigation arrive in D-02 / D-03.</p>
    </section>
  );
};


// ═══════════════════════════════════════════════════════════════════
// 3. Export
// ═══════════════════════════════════════════════════════════════════
export default CaseDetail;

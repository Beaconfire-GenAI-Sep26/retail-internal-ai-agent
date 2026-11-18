// [12a] Cases page — /cases — any logged-in user
// D-01: placeholder (title + "your stores" + link to a sample case) to prove the route works
// D-02: store-scoped case queue from the Domain API (M&I rate, status, start investigation)


// ═══════════════════════════════════════════════════════════════════
// 1. Imports
// ═══════════════════════════════════════════════════════════════════
import { Link } from 'react-router';
import { useSelector } from 'react-redux';
import { selectStoreIds } from '../store/auth/authSelectors';


// ═══════════════════════════════════════════════════════════════════
// 2. Cases component
// ═══════════════════════════════════════════════════════════════════
const Cases = () => {
  // Store grants from /auth/me (C-01 IDs, e.g. STORE-A)
  const storeIds = useSelector(selectStoreIds) ?? [];

  return (
    <section>
      <h1>Cases</h1>
      <p>Your stores: {storeIds.length ? storeIds.join(', ') : 'none granted'}</p>
      <p>The case queue arrives in D-02.</p>
      <Link to='/cases/CASE-0001'>Open sample case CASE-0001 →</Link>
    </section>
  );
};


// ═══════════════════════════════════════════════════════════════════
// 3. Export
// ═══════════════════════════════════════════════════════════════════
export default Cases;

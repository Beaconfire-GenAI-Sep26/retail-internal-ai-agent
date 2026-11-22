// [02] Route table — every page of the app and who is allowed to see it
//
// Route tree (D-01 acceptance: /login, /cases, /cases/:caseId; anonymous → /login)
//   /login                     public
//   AuthGuard                  must be logged in (LOE Analyst or Viewer)
//     /                              → redirect to /monitor (D-06: the landing page)
//     /monitor                       Monitor      store dashboard (D-06)
//     /cases                         Cases        (placeholder now, D-02 fills it)
//     /cases/:caseId                 CaseDetail   (placeholder now, D-02/D-03 fill it)
//   *                          404
// No /register — internal tool, accounts are seeded by the Auth Service (A-02).
// No role guard — both roles may view cases; role only decides which ACTIONS show.


// ═══════════════════════════════════════════════════════════════════
// 1. Imports
// ═══════════════════════════════════════════════════════════════════
import { useEffect } from 'react';
import { Routes, Route, Navigate, Link } from 'react-router';
import { useDispatch } from 'react-redux';

import { bootstrap } from './store/auth/authThunks';
import Layout from './components/Layout';
import AuthGuard from './guards/AuthGuard';
import Login from './pages/Login';
import Monitor from './pages/Monitor';
import Cases from './pages/Cases';
import CaseDetail from './pages/CaseDetail';
import useDocumentTitle from './hooks/useDocumentTitle';

// Unknown URL → a way back instead of a dead end
const NotFound = () => {
  useDocumentTitle('Page not found');
  return (
    <section>
      <h1>Page Not Found</h1>
      <Link to='/'>← Back to the dashboard</Link>
    </section>
  );
};


// ═══════════════════════════════════════════════════════════════════
// 2. App component
// ═══════════════════════════════════════════════════════════════════
function App() {
  const dispatch = useDispatch();

  // ── 2a. Session restore on first load ───────────────────────────
  // Try to restore the session (refresh cookie, or the mock session). Until this
  // settles, AuthGuard shows "Loading…" so a returning analyst isn't flashed to /login.
  useEffect(() => {
    dispatch(bootstrap());
  }, [dispatch]);

  // ── 2b. Routes — see the route tree at the top of this file ─────
  return (
    <Routes>
      <Route path='/' element={<Layout />}>
        {/* Public */}
        <Route path='login' element={<Login />} />

        {/* Any logged-in user */}
        <Route element={<AuthGuard />}>
          <Route index element={<Navigate to='/monitor' replace />} />
          <Route path='monitor' element={<Monitor />} />
          <Route path='cases' element={<Cases />} />
          <Route path='cases/:caseId' element={<CaseDetail />} />
        </Route>

        {/* Unknown URL → a way back instead of a dead end */}
        <Route path='*' element={<NotFound />} />
      </Route>
    </Routes>
  );
}


// ═══════════════════════════════════════════════════════════════════
// 3. Export
// ═══════════════════════════════════════════════════════════════════
export default App;

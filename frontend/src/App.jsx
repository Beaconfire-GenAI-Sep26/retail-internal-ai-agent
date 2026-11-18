// [02] Route table — every page of the app and who is allowed to see it
// Reference: zara-returns-web/src/App.jsx
//
// Route tree (D-01 acceptance: /login, /cases, /cases/:caseId; anonymous → /login)
//   /login                     public
//   AuthGuard                  must be logged in (LOE Analyst or Viewer)
//     /                              → redirect to /cases
//     /cases                         Cases        (placeholder now, D-02 fills it)
//     /cases/:caseId                 CaseDetail   (placeholder now, D-02/D-03 fill it)
//   *                          404
// No /register — internal tool, accounts are seeded by the Auth Service (A-02).


// ═══════════════════════════════════════════════════════════════════
// 1. Imports
// ═══════════════════════════════════════════════════════════════════
// TODO: Routes/Route/Navigate/Link, useDispatch, bootstrap thunk, Layout,
//       AuthGuard, Login, Cases, CaseDetail


// ═══════════════════════════════════════════════════════════════════
// 2. App component
// ═══════════════════════════════════════════════════════════════════

// ── 2a. Session restore on first load ───────────────────────────
// TODO: useEffect → dispatch(bootstrap()) once

// ── 2b. Routes — see the route tree at the top of this file ─────
// TODO: <Route path='/' element={<Layout />}> wrapping the tree above
// For now (commit 1): a placeholder so the app builds and renders
function App() {
  return <h1>M&amp;I Diagnosis Workspace</h1>;
}


// ═══════════════════════════════════════════════════════════════════
// 3. Export
// ═══════════════════════════════════════════════════════════════════
export default App;

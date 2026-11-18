// [09a] AuthGuard — layout route: logged in → <Outlet />, else → /login
// No role guard here: both roles can view cases; role only hides actions
// (approve / reject) in D-03.


// ═══════════════════════════════════════════════════════════════════
// 1. Imports
// ═══════════════════════════════════════════════════════════════════
import { Outlet, Navigate, useLocation } from 'react-router';
import { useSelector } from 'react-redux';
import { selectIsAuthenticated, selectBootstrapped } from '../store/auth/authSelectors';


// ═══════════════════════════════════════════════════════════════════
// 2. AuthGuard component
// ═══════════════════════════════════════════════════════════════════
// UI convenience only — the backend still enforces auth on every request, so a
// forged token just earns 401s from the API.
const AuthGuard = () => {
  const bootstrapped = useSelector(selectBootstrapped);
  const isLoggedIn = useSelector(selectIsAuthenticated);
  const location = useLocation();

  // Step 1: wait for the on-load session restore before deciding, otherwise a
  // returning analyst would be bounced to /login for an instant
  if (!bootstrapped) return <p>Loading…</p>;

  // Step 2: logged in → render the child route, else → /login.
  // `from` lets Login send the analyst back to the page they asked for
  // (e.g. a shared /cases/CASE-0001 link).
  return isLoggedIn ? (
    <Outlet />
  ) : (
    <Navigate to='/login' replace state={{ from: location.pathname }} />
  );
};


// ═══════════════════════════════════════════════════════════════════
// 3. Export
// ═══════════════════════════════════════════════════════════════════
export default AuthGuard;

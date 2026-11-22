// [10a] Layout — app shell: <Nav> beside the current page (D-06)
//   logged in:   side bar on the left, page on the right (.app-shell)
//   logged out:  top bar, page below (the login form)


// ═══════════════════════════════════════════════════════════════════
// 1. Imports
// ═══════════════════════════════════════════════════════════════════
import { Outlet, useLocation } from 'react-router';
import { useSelector } from 'react-redux';
import Nav from './Nav';
import ErrorBoundary from './common/ErrorBoundary';
import { selectIsAuthenticated } from '../store/auth/authSelectors';


// ═══════════════════════════════════════════════════════════════════
// 2. Layout component
// ═══════════════════════════════════════════════════════════════════
// Layout route: renders <Nav> on every page, with the matched child route shown
// in the <Outlet>. A crash inside the page stays inside <main> (ErrorBoundary).
const Layout = () => {
  const isLoggedIn = useSelector(selectIsAuthenticated);
  const { pathname } = useLocation();
  return (
    <div className={isLoggedIn ? 'app-shell' : undefined}>
      <Nav />
      <main>
        <ErrorBoundary resetKey={pathname}>
          <Outlet />
        </ErrorBoundary>
      </main>
    </div>
  );
};


// ═══════════════════════════════════════════════════════════════════
// 3. Export
// ═══════════════════════════════════════════════════════════════════
export default Layout;

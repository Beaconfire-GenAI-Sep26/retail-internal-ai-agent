// [10a] Layout — app shell: <Nav> beside the current page (D-06)
//   logged in:   side bar on the left, page on the right (.app-shell)
//   logged out:  top bar, page below (the login form)


// ═══════════════════════════════════════════════════════════════════
// 1. Imports
// ═══════════════════════════════════════════════════════════════════
import { useEffect, useRef } from 'react';
import { Outlet, useLocation, useNavigationType } from 'react-router';
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
  const navigationType = useNavigationType();
  const mainRef = useRef(null);
  const firstRender = useRef(true);

  // ── 2a. New page → start at the top, focus on the page ──────────
  // An SPA keeps the old scroll position, and keyboard focus stays on the
  // link that was clicked (often gone now). On a new page: scroll to the top
  // and focus <main>, so the next Tab lands in the page and a screen reader
  // starts reading there. Only the path counts: filters in ?query and #anchors
  // (check links) stay put. Back/Forward (POP) keeps the scroll; the first load
  // doesn't steal focus from the browser.
  useEffect(() => {
    if (firstRender.current) {
      firstRender.current = false;
      return;
    }
    if (navigationType === 'POP') return;
    window.scrollTo(0, 0);
    mainRef.current?.focus({ preventScroll: true });
  }, [pathname]); // eslint-disable-line react-hooks/exhaustive-deps -- navigationType is read, not a trigger

  return (
    <div className={isLoggedIn ? 'app-shell' : undefined}>
      <Nav />
      {/* tabIndex -1: focusable from code only, not a Tab stop */}
      <main ref={mainRef} tabIndex={-1}>
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

// [10a] Layout — app shell: <Nav> on top, the current page below


// ═══════════════════════════════════════════════════════════════════
// 1. Imports
// ═══════════════════════════════════════════════════════════════════
import { Outlet } from 'react-router';
import Nav from './Nav';


// ═══════════════════════════════════════════════════════════════════
// 2. Layout component
// ═══════════════════════════════════════════════════════════════════
// Layout route: renders <Nav> on every page, with the matched child route shown
// in the <Outlet>.
const Layout = () => (
  <>
    <Nav />
    <main>
      <Outlet />
    </main>
  </>
);


// ═══════════════════════════════════════════════════════════════════
// 3. Export
// ═══════════════════════════════════════════════════════════════════
export default Layout;

// [10b] Nav — side bar when logged in, top bar when logged out (D-06)
//   logged out:  brand only (top bar)
//   logged in:   brand · Monitor · Cases  ...  [Reset demo] · display_name · role · Logout
//                a column on the left; a top bar again on small screens (index.css section 14):
//     ≤960px   one row; the name is hidden (Logout's tooltip keeps it)
//     ≤600px   two rows: brand ... [Reset demo] role Logout
//                        [ Monitor ][ Cases ]   ← full-width tabs
//     ≤440px   the role is hidden too
//   Reset demo shows only with VITE_USE_MOCKS=true
//   first group = where to go, second group = who is signed in


// ═══════════════════════════════════════════════════════════════════
// 1. Imports
// ═══════════════════════════════════════════════════════════════════
import { NavLink, useNavigate } from 'react-router';
import { useDispatch, useSelector } from 'react-redux';
import { logout } from '../store/auth/authThunks';
import { USE_MOCKS } from '../api/mockAuth';
import { resetMocks } from '../api/mocks/mockInvestigations';
import {
  selectIsAuthenticated,
  selectIsAnalyst,
  selectUser,
} from '../store/auth/authSelectors';


// Line icons for the nav links (decorative — the link text names the page)
const Icon = ({ d }) => (
  <svg className='nav-icon' viewBox='0 0 24 24' aria-hidden='true' fill='none' stroke='currentColor'
    strokeWidth='2' strokeLinecap='round' strokeLinejoin='round'>
    <path d={d} />
  </svg>
);
const MONITOR_ICON = 'M3 3v18h18M7 14l4-4 3 3 5-6';
const CASES_ICON = 'M5 4h14a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2zM3 9h18M8 14h8';


// ═══════════════════════════════════════════════════════════════════
// 2. Nav component
// ═══════════════════════════════════════════════════════════════════
const Nav = () => {
  // ── 2a. Hooks + auth state ──────────────────────────────────────
  // useSelector re-renders the nav whenever login state changes
  const dispatch = useDispatch();
  const navigate = useNavigate();
  const isLoggedIn = useSelector(selectIsAuthenticated);
  const isAnalyst = useSelector(selectIsAnalyst);
  const user = useSelector(selectUser);

  // ── 2b. Handlers ────────────────────────────────────────────────
  const handleLogout = async () => {
    // Wait for the thunk so the store is logged out before navigating
    await dispatch(logout());
    navigate('/login');
  };

  // Mock mode only: forget every mock investigation, proposal, recheck and audit
  // row, so each case is back to "not started" (its real Domain status). The
  // page reloads to drop what Redux already holds; the mock login survives it.
  const handleResetDemo = () => {
    if (!window.confirm('Reset the demo? All mock investigations, decisions and rechecks are cleared.')) return;
    resetMocks();
    window.location.reload();
  };

  // ── 2c. Render ──────────────────────────────────────────────────
  const userName = user?.display_name ?? user?.username;
  const roleLabel = isAnalyst ? 'LOE Analyst' : 'Viewer';

  return (
    <nav className='nav'>
      <div className='nav-left'>
        <strong className='nav-brand'>M&amp;I Diagnosis</strong>
        {isLoggedIn && (
          <>
            <NavLink to='/monitor'><Icon d={MONITOR_ICON} />Monitor</NavLink>
            <NavLink to='/cases'><Icon d={CASES_ICON} />Cases</NavLink>
          </>
        )}
      </div>

      {isLoggedIn && (
        <div className='nav-user'>
          {USE_MOCKS && (
            <button type='button' className='button-secondary nav-reset' onClick={handleResetDemo} title='Mock data: start every case over'>
              Reset demo
            </button>
          )}
          <span className='nav-name'>{userName}</span>
          <span className='nav-role'>{roleLabel}</span>
          {/* On small screens the name (and on phones the role) are hidden; the tooltip keeps them */}
          <button type='button' className='button-secondary' onClick={handleLogout}
            title={`Signed in as ${userName} (${roleLabel})`}>Logout</button>
        </div>
      )}
    </nav>
  );
};


// ═══════════════════════════════════════════════════════════════════
// 3. Export
// ═══════════════════════════════════════════════════════════════════
export default Nav;

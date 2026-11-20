// [10b] Nav — top bar
//   logged out:  brand only
//   logged in:   brand · Cases  ...  [Reset demo] · display_name · role (LOE Analyst / Viewer) · Logout
//   Reset demo shows only with VITE_USE_MOCKS=true
//   left group = where to go, right group = who is signed in (index.css section 2)


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
  return (
    <nav className='nav'>
      <div className='nav-left'>
        <strong className='nav-brand'>M&amp;I Diagnosis</strong>
        {isLoggedIn && <NavLink to='/cases'>Cases</NavLink>}
      </div>

      {isLoggedIn && (
        <div className='nav-user'>
          {USE_MOCKS && (
            <button type='button' className='button-secondary nav-reset' onClick={handleResetDemo} title='Mock data: start every case over'>
              Reset demo
            </button>
          )}
          <span>{user?.display_name ?? user?.username}</span>
          <span className='nav-role'>{isAnalyst ? 'LOE Analyst' : 'Viewer'}</span>
          <button type='button' className='button-secondary' onClick={handleLogout}>Logout</button>
        </div>
      )}
    </nav>
  );
};


// ═══════════════════════════════════════════════════════════════════
// 3. Export
// ═══════════════════════════════════════════════════════════════════
export default Nav;

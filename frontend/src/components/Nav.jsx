// [10b] Nav — top bar
//   logged out:  brand only
//   logged in:   Cases · display_name · role (LOE Analyst / Viewer) · Logout


// ═══════════════════════════════════════════════════════════════════
// 1. Imports
// ═══════════════════════════════════════════════════════════════════
import { NavLink, useNavigate } from 'react-router';
import { useDispatch, useSelector } from 'react-redux';
import { logout } from '../store/auth/authThunks';
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

  // ── 2c. Render ──────────────────────────────────────────────────
  return (
    <nav>
      <strong>M&amp;I Diagnosis</strong>
      {isLoggedIn && (
        <>
          {' · '}
          <NavLink to='/cases'>Cases</NavLink>
          {' · '}
          <span>{user?.display_name ?? user?.username}</span>
          {' · '}
          <span>{isAnalyst ? 'LOE Analyst' : 'Viewer'}</span>
          {' · '}
          <button type='button' onClick={handleLogout}>Logout</button>
        </>
      )}
    </nav>
  );
};


// ═══════════════════════════════════════════════════════════════════
// 3. Export
// ═══════════════════════════════════════════════════════════════════
export default Nav;

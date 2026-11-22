// [11a] Login page — /login — public
// Login uses username; no Register link (accounts are seeded by the Auth Service)


// ═══════════════════════════════════════════════════════════════════
// 1. Imports
// ═══════════════════════════════════════════════════════════════════
import { useState } from 'react';
import { Navigate, useLocation } from 'react-router';
import { useDispatch, useSelector } from 'react-redux';
import { login } from '../store/auth/authThunks';
import { USE_MOCKS } from '../api/mockAuth';
import {
  selectLoginError,
  selectAuthStatus,
  selectIsAuthenticated,
} from '../store/auth/authSelectors';


// ═══════════════════════════════════════════════════════════════════
// 2. Login component
// ═══════════════════════════════════════════════════════════════════
const Login = () => {
  // ── 2a. Form state (local — only this form cares) ───────────────
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');

  // ── 2b. Hooks + auth state from Redux ───────────────────────────
  const dispatch = useDispatch();
  const location = useLocation();
  const error = useSelector(selectLoginError);
  const status = useSelector(selectAuthStatus);
  const isLoggedIn = useSelector(selectIsAuthenticated);

  // ── 2c. Submit handler ──────────────────────────────────────────
  // No navigate() here: on success the slice stores the token → isLoggedIn turns
  // true → the redirect in the render below takes over.
  const submit = (e) => {
    e.preventDefault();
    dispatch(login({ username, password }));
  };

  // ── 2d. Render ──────────────────────────────────────────────────
  // Logged in — just now, or already (typed /login, back button)
  // → back to the page AuthGuard bounced them from, else the case queue
  if (isLoggedIn) return <Navigate to={location.state?.from ?? '/monitor'} replace />;

  const loading = status === 'loading';

  return (
    <form onSubmit={submit}>
      <h1>Sign in</h1>
      <p>Internal workspace for Merchant LOE analysts.</p>

      <label>
        Username
        <input
          autoComplete='username'
          value={username}
          onChange={(e) => setUsername(e.target.value)}
          required
        />
      </label>

      <label>
        Password
        <input
          type='password'
          autoComplete='current-password'
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          required
        />
      </label>

      {error && <p role='alert'>{error}</p>}

      <button type='submit' disabled={loading}>
        {loading ? 'Signing in…' : 'Sign in'}
      </button>

      {/* Only in mock mode — tells teammates which demo accounts exist */}
      {USE_MOCKS && (
        <p>
          Mock mode · analyst / Password123! (STORE-A, STORE-B) · viewer / Password123! (STORE-A)
        </p>
      )}
    </form>
  );
};


// ═══════════════════════════════════════════════════════════════════
// 3. Export
// ═══════════════════════════════════════════════════════════════════
export default Login;

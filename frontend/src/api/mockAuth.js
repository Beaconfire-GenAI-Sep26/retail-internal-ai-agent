// [03c] Mock Auth — used only when VITE_USE_MOCKS=true, until A-02 is ready
//
// Real contract (docs/contracts.md, B-01 v0.3):
//   POST /auth/login   { username, password } → { access_token, token_type, expires_at, user }
//   GET  /auth/me      → User
//   User = { user_id, display_name, role, store_ids }   role: 'loe_analyst' | 'viewer'
// The mock functions return the SAME shape authThunks builds from the real API:
//   { token, user: User, expiresAt }


// ═══════════════════════════════════════════════════════════════════
// 1. Switch + demo accounts
// ═══════════════════════════════════════════════════════════════════
// Env values are strings → compare with 'true'
export const USE_MOCKS = import.meta.env.VITE_USE_MOCKS === 'true';

const DEMO_PASSWORD = 'Password123!';

// Roles (contract `role` enum): 'loe_analyst' = LOE Analyst (investigate, decide drafts)
//                               'viewer'      = read only
// store_ids use the C-01 seed IDs:
//   STORE-A → POS modifier case · STORE-B → dinner packing case
// The Viewer is granted only STORE-A so the demo can show a denied STORE-B
// read and a denied approval.
// `username` is only the login name the mock matches on. The contract's User has
// no username, so only `user` is returned to the app.
const DEMO_ACCOUNTS = [
  {
    username: 'analyst',
    user: {
      user_id: 'USR-001',
      display_name: 'Demo LOE Analyst',
      role: 'loe_analyst',
      store_ids: ['STORE-A', 'STORE-B'],
    },
  },
  {
    username: 'viewer',
    user: {
      user_id: 'USR-002',
      display_name: 'Demo Viewer',
      role: 'viewer',
      store_ids: ['STORE-A'],
    },
  },
];

const findAccount = (username) => DEMO_ACCOUNTS.find((a) => a.username === username);


// ═══════════════════════════════════════════════════════════════════
// 2. Fake session — sessionStorage stands in for the refresh cookie
// ═══════════════════════════════════════════════════════════════════
// Mock only: the real app keeps the token in memory and restores it via
// /auth/refresh. sessionStorage just lets a hard refresh keep you logged in
// during local dev. Storage can throw (private mode), so every access is guarded.
const SESSION_KEY = 'mock-auth-username';

const saveSession = (username) => {
  try {
    sessionStorage.setItem(SESSION_KEY, username);
  } catch {
    // ignore — the mock session just won't survive a reload
  }
};

const readSession = () => {
  try {
    return sessionStorage.getItem(SESSION_KEY);
  } catch {
    return null;
  }
};

const clearSession = () => {
  try {
    sessionStorage.removeItem(SESSION_KEY);
  } catch {
    // ignore
  }
};

// Small delay so loading states ("Signing in…") are visible like a real call
const delay = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const fakeToken = (user) => `mock.${user.user_id}.${Date.now()}`;
// Same lifetime as the real token (JWT_TTL_MINUTES = 60 in architecture.md)
const fakeExpiresAt = () => new Date(Date.now() + 60 * 60 * 1000).toISOString();


// ═══════════════════════════════════════════════════════════════════
// 3. Mock endpoints — mockLogin / mockBootstrap / mockLogout
// ═══════════════════════════════════════════════════════════════════
// Errors are thrown as plain Error(message); authThunks passes err.message to
// rejectWithValue in mock mode.
export const mockLogin = async ({ username, password }) => {
  await delay(300);
  const account = findAccount(username);
  if (!account || password !== DEMO_PASSWORD) {
    throw new Error('Invalid username or password');
  }
  saveSession(account.username);
  return { token: fakeToken(account.user), user: account.user, expiresAt: fakeExpiresAt() };
};

export const mockBootstrap = async () => {
  await delay(100);
  const account = findAccount(readSession());
  if (!account) throw new Error('No session');
  return { token: fakeToken(account.user), user: account.user, expiresAt: fakeExpiresAt() };
};

export const mockLogout = async () => {
  clearSession();
};

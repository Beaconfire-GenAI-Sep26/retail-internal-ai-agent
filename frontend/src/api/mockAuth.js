// [03c] Mock Auth — used only when VITE_USE_MOCKS=true, until A-02 is ready
//
// Planned real contract (confirm with B-01 / A-02):
//   POST /auth/login   { username, password } → { access_token, token_type }
//   GET  /auth/me      → { id, username, display_name, role, store_ids }
//   POST /auth/refresh → { access_token }          (HttpOnly refresh cookie)
//   POST /auth/logout  → 204
// The mock functions return the SAME shape authThunks builds from the real API:
//   { token, user: { id, username, display_name, role, store_ids } }


// ═══════════════════════════════════════════════════════════════════
// 1. Switch + demo accounts
// ═══════════════════════════════════════════════════════════════════
// Env values are strings → compare with 'true'
export const USE_MOCKS = import.meta.env.VITE_USE_MOCKS === 'true';

const DEMO_PASSWORD = 'Password123!';

// Roles (sprint plan): 'analyst' = LOE Analyst (investigate, decide drafts)
//                      'viewer'  = read only
// store_ids use the C-01 seed IDs:
//   STORE-A → POS modifier case · STORE-B → dinner packing case
// The Viewer is granted only STORE-A so the demo can show a denied STORE-B
// read and a denied approval.
export const DEMO_USERS = [
  {
    id: 1,
    username: 'analyst',
    display_name: 'Demo LOE Analyst',
    role: 'analyst',
    store_ids: ['STORE-A', 'STORE-B'],
  },
  {
    id: 2,
    username: 'viewer',
    display_name: 'Demo Viewer',
    role: 'viewer',
    store_ids: ['STORE-A'],
  },
];


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
const fakeToken = (user) => `mock.${user.username}.${Date.now()}`;


// ═══════════════════════════════════════════════════════════════════
// 3. Mock endpoints — mockLogin / mockBootstrap / mockLogout
// ═══════════════════════════════════════════════════════════════════
// Errors are thrown as plain Error(message); authThunks passes err.message to
// rejectWithValue in mock mode.
export const mockLogin = async ({ username, password }) => {
  await delay(300);
  const user = DEMO_USERS.find((u) => u.username === username);
  if (!user || password !== DEMO_PASSWORD) {
    throw new Error('Invalid username or password');
  }
  saveSession(user.username);
  return { token: fakeToken(user), user };
};

export const mockBootstrap = async () => {
  await delay(100);
  const user = DEMO_USERS.find((u) => u.username === readSession());
  if (!user) throw new Error('No session');
  return { token: fakeToken(user), user };
};

export const mockLogout = async () => {
  clearSession();
};

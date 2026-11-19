import axios from 'axios';
import { sessionRefreshed, credentialsCleared } from '../store/auth/authSlice';
import { selectToken } from '../store/auth/authSelectors';

let store;
export const injectStore = (value) => { store = value; };

const api = axios.create({
  baseURL: import.meta.env.VITE_API_URL ?? '',
  withCredentials: true,
});

api.interceptors.request.use((config) => {
  const token = store ? selectToken(store.getState()) : null;
  // Explicit credentials (if supplied) must not be overwritten by a stale token.
  if (token && !config.headers.Authorization) config.headers.Authorization = `Bearer ${token}`;
  return config;
});

let refreshPromise = null;
let generation = 0;

// Login/logout invalidate any older refresh result. The caller waits for its
// cookie response before changing sessions, preventing a late refresh resurrection.
export const invalidateSession = () => {
  generation += 1;
  const pending = refreshPromise;
  refreshPromise = null;
  return pending;
};

// Shared by page-load bootstrap and 401 recovery, including React StrictMode.
export const refreshSession = () => {
  if (!refreshPromise) {
    const started = generation;
    const pending = axios.post(`${api.defaults.baseURL}/auth/refresh`, null, {
      withCredentials: true,
    }).then(({ data }) => {
      if (started !== generation) throw new Error('Session changed during refresh');
      store?.dispatch(sessionRefreshed({ token: data.access_token, user: data.user }));
      return data;
    }).finally(() => {
      if (refreshPromise === pending) refreshPromise = null;
    });
    refreshPromise = pending;
  }
  return refreshPromise;
};

api.interceptors.response.use(
  (response) => response,
  async (error) => {
    const original = error.config;
    const authEndpoint = /^\/?auth\/(login|refresh|logout)(?:\?|$)/.test(original?.url ?? '');
    if (!original || error.response?.status !== 401 || authEndpoint || !store) {
      return Promise.reject(error);
    }
    const token = selectToken(store.getState());
    // A request started before logout must not silently restore the session.
    if (!token) return Promise.reject(error);
    if (original._retry) {
      store.dispatch(credentialsCleared());
      return Promise.reject(error);
    }
    original._retry = true;
    const started = generation;
    try {
      // A late 401 for the old token can reuse a refresh that already finished.
      const used = original.headers.Authorization;
      const newToken = used && used !== `Bearer ${token}`
        ? token : (await refreshSession()).access_token;
      if (started !== generation) return Promise.reject(error);
      original.headers.Authorization = `Bearer ${newToken}`;
      return api(original);
    } catch (refreshError) {
      if (started === generation) store.dispatch(credentialsCleared());
      return Promise.reject(refreshError);
    }
  },
);

export default api;

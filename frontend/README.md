# Frontend: Analyst Workspace

React app for LOE analysts to sign in, follow M&I cases, review agent diagnoses and approve or reject actions.

**Stack:** React 19 · React Router · Redux Toolkit · Axios · Vite · Docker · Nginx

## Run locally

Requires Node 20.19+ (the Docker image uses Node 24).

```bash
cd frontend
cp .env.example .env    # mock login is on by default
npm install
npm run dev             # http://localhost:5173
```

Other commands: `npm run build` (output in `dist/`), `npm run lint`, `npm run preview`.

## Environment variables

Vite bakes `VITE_*` values into the JavaScript at build time, so changing one needs a dev-server restart or a rebuild.

| Variable | Default | Meaning |
| --- | --- | --- |
| `VITE_API_URL` | empty | Base URL for API calls. Empty means same origin: requests go to `/auth`, `/agent` and `/domain` on the API Gateway. For local dev against a running gateway, set it to that address, for example `http://localhost`. |
| `VITE_USE_MOCKS` | `true` in `.env.example`, `false` in Docker | `true` uses the demo accounts in `src/api/mockAuth.js` instead of the Auth Service. Set it to `false` once A-02 is running. |

## Mock accounts

Used only when `VITE_USE_MOCKS=true`. Store IDs match the Domain seed (C-01).

| Username | Password | Role | Stores |
| --- | --- | --- | --- |
| `analyst` | `Password123!` | LOE Analyst | STORE-A, STORE-B |
| `viewer` | `Password123!` | Viewer (read only) | STORE-A |

## Docker

```bash
docker build -t retail-frontend ./frontend
docker run --rm -p 8080:80 retail-frontend    # http://localhost:8080
```

Add `--build-arg VITE_USE_MOCKS=true` to try the image without the Auth Service, or `--build-arg VITE_API_URL=...` to point at another gateway.

The image is a two-stage build: Node runs `npm ci` and `npm run build`, then `nginx:alpine` serves `dist/`. `nginx.conf` only serves the app: any unknown path falls back to `index.html` so a refresh on `/cases/CASE-0001` works. API routing is done by the API Gateway, not by this container.

## Routes

| Path | Access | Page |
| --- | --- | --- |
| `/login` | public | Sign in |
| `/` | logged in | Redirects to `/cases` |
| `/cases` | logged in | Case queue (placeholder until D-02) |
| `/cases/:caseId` | logged in | Case detail, for example `/cases/CASE-0001` (placeholder until D-02/D-03) |

Anonymous visitors are sent to `/login` and returned to the page they asked for after signing in. Both roles can open every page. The role only controls which actions appear (D-03), and the backend checks role and store grant on every request.

## Auth contract the frontend expects

To be confirmed against the B-01 contracts and A-02:

| Endpoint | Request | Response |
| --- | --- | --- |
| `POST /auth/login` | `{ username, password }` | `{ access_token, token_type }`, or 401 |
| `GET /auth/me` | Bearer token | `{ id, username, display_name, role, store_ids }`, where `role` is `analyst` or `viewer` |
| `POST /auth/refresh` | HttpOnly refresh cookie | `{ access_token }`, or 401 |
| `POST /auth/logout` | HttpOnly refresh cookie | 204 |

The access token is kept in memory (Redux) only. On a page load the app calls `/auth/refresh` to restore the session. On a 401 from any other call it refreshes once and retries; if the refresh fails, it returns to `/login`.

## Folder structure

```
src/
  main.jsx            Providers: Redux store + router
  App.jsx             Route table
  api/
    axios.js          Shared axios instance: base URL, Bearer token, 401 refresh
    errors.js         getErrorMessage(err): one readable message per error
    mockAuth.js       Mock Auth Service (VITE_USE_MOCKS=true)
  store/
    store.js          configureStore
    auth/             authThunks · authSlice · authSelectors
  guards/
    AuthGuard.jsx     Logged in → page, else → /login
  components/         Layout, Nav
  pages/              Login, Cases, CaseDetail
```

Each feature in `store/` uses three files: thunks (API calls), slice (state), selectors (reads). Components never call axios directly.

## Notes

- **`npm ci` fails in Docker with "Missing ... from lock file":** the lock file was written by an older npm on macOS and is missing platform-specific optional packages. Refresh it with the image's npm version: `npx npm@<version> install --package-lock-only`, using the version from `docker run --rm node:24-alpine npm -v`.
- **`npm audit` reports `picomatch` (high):** it comes through Vite and is a build-time-only dependency. The suggested `npm audit fix --force` downgrades Vite, so it is not applied.

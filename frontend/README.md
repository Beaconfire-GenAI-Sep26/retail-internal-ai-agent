# Frontend: Analyst Workspace

React app for LOE analysts to sign in, follow M&I cases, review agent diagnoses and approve or reject actions.

**Stack:** React 19 · React Router · Redux Toolkit · Axios · Vite · Docker · Nginx

## Run locally

Requires Node 20.19+ (the Docker image uses Node 24). Run these Bash commands
on macOS from the repository root:

```bash
cd frontend
if [ ! -f .env ]; then
  cp .env.example .env    # real auth by default; gateway at localhost:18080
fi
npm ci
npm run dev             # http://localhost:5173
```

Other commands: `npm test`, `npm run build` (output in `dist/`), `npm run lint`, `npm run preview`.

## Environment variables

Vite bakes `VITE_*` values into the JavaScript at build time, so changing one needs a dev-server restart or a rebuild.

| Variable | Default | Meaning |
| --- | --- | --- |
| `VITE_API_URL` | empty | Same-origin API paths. In local Vite development the dev server proxies them to `http://localhost:18080`, preserving cookie and Origin behavior. |
| `VITE_USE_MOCKS` | `false` | Set `true` explicitly for standalone UI development using mock accounts. |

## Mock accounts

Used only when `VITE_USE_MOCKS=true`. Store IDs match the Domain seed (C-01).

| Username | Password | Role | Stores |
| --- | --- | --- | --- |
| `analyst` | `Password123!` | LOE Analyst | STORE-A, STORE-B |
| `viewer` | `Password123!` | Viewer (read only) | STORE-A |

## Docker

Run from the repository root:

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
| `/` | logged in | Redirects to `/monitor` |
| `/monitor` | logged in | Store dashboard (D-06): M&I rate trend with operational events, KPIs vs the previous period, error categories, dayparts, top items, cancellations, review status. Store and order data only. With `VITE_USE_MOCKS=true` the data comes from `src/api/mocks/mockStores.js` |
| `/cases` | logged in | Case queue; `?store_id=STORE-A` preselects the store filter (used by the Monitor's "View cases" links) |
| `/cases/:caseId` | logged in | Case detail, for example `/cases/CASE-0001` (placeholder until D-02/D-03) |

Anonymous visitors are sent to `/login` and returned to the page they asked for after signing in. Both roles can open every page. The role only controls which actions appear (D-03), and the backend checks role and store grant on every request.

## Auth contract the frontend expects

Implemented by A-02; see [the shared contract](../docs/contracts.md#auth-service).

| Endpoint | Request | Response |
| --- | --- | --- |
| `POST /auth/login` | `{ username, password }` | `{ access_token, token_type, expires_at, user }`, sets refresh cookie; or 401 |
| `GET /auth/me` | Bearer token | `{ user_id, display_name, role, store_ids }`, where `role` is `loe_analyst` or `viewer` |
| `POST /auth/refresh` | HttpOnly refresh cookie | Same payload as login; rotates cookie; or 401 |
| `POST /auth/logout` | HttpOnly refresh cookie | 204 |

The access token is kept in memory (Redux) only. On a page load the app calls `/auth/refresh` to restore the session. Concurrent 401s share one refresh and retry once; if refresh fails, AuthGuard returns to `/login`. Login/logout failures and 403s never trigger refresh. Login and refresh both provide the complete user profile, including current store grants.

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

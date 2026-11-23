# Domain Service

FastAPI service with JWT/store access control, SQLAlchemy models, migrations and
repeatable synthetic data for 15 stores (Oct 5 - Nov 15, 2026), plus the C-04 golden dataset and the C-05 future snapshot for rechecks. The entry point is
`domain.app.main:app`; Compose builds this directory together with `shared/`.

The app mounts C-02's case, evidence, monitor and diagnostic routers and C-03's
proposal, catalog and internal routers behind
the shared JWT/default-deny boundary. ORM sessions use the app's configured
engine, and query principals inherit its narrowed store grants. Cross-service
tests and the graph run from the repository root with qualified package imports.

Database-backed tests require `DOMAIN_TEST_DATABASE_URL` naming a separate seeded
`retail_merge_test_*` database; they clear test cases and must not use app data.
Run all commands below in Bash on macOS from the repository root.

## Files

| Path | What it is |
| --- | --- |
| `app/main.py`, `app/access.py` | API entry point, health/readiness, store/menu reads and default-deny authorization |
| `app/db.py` | Administrative engine/session using the same shared configuration as the API |
| `app/models.py` | 21 tables: 19 in schema `domain`; the answer key (`golden_scenarios`, `workflow_scenarios`) in schema `eval` |
| `app/routers/`, `app/services/` | C-02 cases, monitor, diagnostics, evidence; C-03 proposals, decisions, mock dispatch, audit; C-05 merchant replies, rechecks |
| `app/catalog.py` | Action catalog (same IDs as the agent's `catalog.json` fixture) |
| `scripts/make_demo_token.py` | Prints a local demo JWT |
| `alembic.ini`, `migrations/` | Alembic migrations; the version table lives in schema `domain` |
| `scripts/reset_and_seed.py` | Drops both schemas, runs `alembic upgrade head`, then loads seed data (fixed seed 24) |
| `scripts/check_seed.py` | Row counts, integrity checks (incl. golden evidence IDs) and M&I rate per store |
| `scripts/scenario_stores.py` | C-04 builder for scenario stores, and the dev stores K-M (GS-05..07) |
| `scripts/workflow_scenarios.py` | C-04 workflow and safety scenarios W-01..W-05 |
| `scripts/future_snapshot.py` | C-05 future snapshot (Nov 16 - Dec 13) and each store's mock merchant answer |
| `tests/test_workflow_scenarios.py` | Runs W-01..W-05 against the API |
| `tests/test_replies_rechecks.py` | C-05 merchant replies and rechecks |

## Run the API

```bash
docker compose up --build domain
```

Compose uses `domain_svc`, restricted to the `domain` schema. Auth/Agent share
the JWT verification code in `shared/`; Domain independently verifies forwarded
tokens and resolves case/proposal ownership before authorizing a request.

Direct development uses `uvicorn domain.app.main:app --root-path /domain` from the repository root
with `JWT_SECRET`, `INTERNAL_SERVICE_TOKEN` and the Domain database environment
configured. The root `.env` is loaded by Compose, not automatically by Python.

### Local demo without the Auth service

From the repository root:

```bash
export JWT_SECRET="change-me-32-bytes-min-local-only"   # must match the Auth service
export INTERNAL_SERVICE_TOKEN="change-me-internal"     # must match the Agent service
uvicorn domain.app.main:app --reload --port 8003
```

Open http://localhost:8003/docs. Print a token signed with the same `JWT_SECRET` and paste it into
**Authorize** (`loe_analyst`, stores A-R, valid 12 hours):

```bash
python -m domain.scripts.make_demo_token
```

## Tests

Tests need a separate seeded database whose name starts with `retail_merge_test_`:

```bash
export DATABASE_URL="postgresql+psycopg://postgres:postgres@localhost:5432/retail_merge_test_domain"
export DOMAIN_TEST_DATABASE_URL="$DATABASE_URL"
python -m domain.scripts.reset_and_seed
python -m pytest -q domain/tests
```

## Migrate and seed

For an existing Docker Compose database, run `make up` to apply pending migrations
and restore runtime grants without clearing data. For the demo seed, run `make reset`
from the repository root. It stops
active application services, clears Agent checkpoints, reseeds Domain, restores
permissions, and restarts the stack while preserving Auth accounts. See the
[Make commands](../README.md#make-commands-for-the-demo). The manual commands below
are for individual administrative operations.

Migrations and evaluation data require an administrative database identity.
Runtime Domain deliberately has no access to `eval`. Starting the API does not
run administrative migrations or reset data.

1. Start PostgreSQL (skip if the project's docker compose already runs it):

   ```bash
   docker run --name retail-pg -e POSTGRES_PASSWORD=postgres -e POSTGRES_DB=retail -p 5432:5432 -d postgres:16
   ```

2. Create a Python 3.12 virtual environment, install dependencies and configure the database:

   ```bash
   python3.12 -m venv .venv
   source .venv/bin/activate
   python -m pip install -r domain/requirements.txt
   export DATABASE_URL="postgresql+psycopg://postgres:postgres@localhost:5432/retail"
   ```

3. Create or upgrade the tables explicitly as an administrator:

   ```bash
   alembic -c domain/alembic.ini upgrade head
   ```

4. Reset and seed demo data, then check:

   ```bash
   python -m domain.scripts.reset_and_seed
   python -m domain.scripts.check_seed
   ```

   Running the reset again deletes everything in `domain` and `eval` and produces
   identical data. After an admin reset against the Compose database, rerun the
   platform role script to restore Domain runtime grants:

   ```bash
   docker compose exec postgres sh /docker-entrypoint-initdb.d/001-service-roles.sh
   ```

For administrative operations on the Compose database without exposing Postgres
on a host port, run the service image on its Docker network. This example runs
only the non-destructive migration command, overriding the service's credentials
with administrator values exported in the shell:

```bash
export POSTGRES_USER='your-existing-admin-user'
export POSTGRES_PASSWORD='your-existing-admin-password'
docker compose run --rm --no-deps -e POSTGRES_USER -e POSTGRES_PASSWORD domain alembic -c domain/alembic.ini upgrade head
```

Replace the example administrator values with your existing local configuration.
Never give the running Domain API the administrator's credentials.

## Changing a table

1. Edit `domain/app/models.py`.
2. Run `alembic -c domain/alembic.ini revision --autogenerate -m "describe the change"` and review `domain/migrations/versions/`.
3. Run `alembic -c domain/alembic.ini upgrade head`, then commit the model change and migration together.

## Cases, monitor and diagnostic tools (C-02)

### Endpoints in C-02

| Method and path | Who | Notes |
| --- | --- | --- |
| `GET /cases?status=&store_id=` | viewer, analyst | Permitted stores only, newest first |
| `GET /cases/{case_id}` | viewer, analyst | Daily rates for the 42 days ending on the trigger window. Other stores' cases are 404 |
| `POST /monitor/run` | analyst | Body `{"as_of": "2026-11-15"}` or empty; `Idempotency-Key` header required |
| `GET /stores/{id}`, `GET /stores/{id}/menu` | any user | 403 `STORE_NOT_PERMITTED` outside the token's stores |
| `GET /stores/{id}/overview?start=&end=` | any user | store_overview |
| `GET /stores/{id}/diagnostics/events?start=&end=&event_type=` | any user | event_log |
| `POST /stores/{id}/diagnostics/claim-breakdown` | any user | claim_breakdown |
| `POST /stores/{id}/diagnostics/compare-periods` | any user | compare_periods |
| `POST /stores/{id}/diagnostics/evidence-sample` | any user | sample_evidence |
| `POST /stores/{id}/diagnostics/cancellation-breakdown` | any user | cancellation_breakdown |
| `GET /stores/{id}/diagnostics/fraud-signals?start=&end=` | any user | fraud_signals |
| `GET /evidence/{evidence_id}` | any user | Evidence lookup |
| `POST /evidence/resolve` | agent only | Checks cited IDs. Needs `X-Service-Token` + user JWT; a browser call gets 403 `SERVICE_TOKEN_INVALID` |

Without `start`/`end`, a tool uses the 42 days ending on the store's last day of data.
Merchant replies, running rechecks and reopening: see C-05 below.

### Monitor rule

For each store in the caller's grants, with `as_of` as the last day (default: the last day of data):

- Window: the 7 days ending on `as_of`. Baseline: the 28 days before the window. Dates are store local.
- Rate = store-attributable claims (`store_fault` + `pending`) / delivered orders.
- Skipped when the store already has a case that is not `closed` (`open_case_exists`), when a closed
  case already covers part of the 7-day window (`already_reviewed`: the demo data is static, so a rerun
  after closing would otherwise reopen the same spike), or when the window has fewer than
  `MONITOR_MIN_ORDERS` delivered orders (`low_volume`).
- Opens a case with status `open` when the rate is above `MONITOR_GOAL_RATE` (`over_goal`), or when it is
  at least `MONITOR_SPIKE_RATIO` x the baseline and at least `MONITOR_MIN_RISE` above it (`spike_vs_baseline`).
  Otherwise the store is listed with `below_threshold`.

| Variable | Default | Meaning |
| --- | --- | --- |
| `MONITOR_GOAL_RATE` | 0.05 | 7-day rate above this opens a case |
| `MONITOR_SPIKE_RATIO` | 1.5 | ...or this multiple of the baseline |
| `MONITOR_MIN_RISE` | 0.03 | ...and at least 3 points above it |
| `MONITOR_MIN_ORDERS` | 100 | Minimum delivered orders in the 7-day window |
| `MIN_GROUP_ORDERS` | 30 | Groups with fewer eligible orders get a null rate |
| `FRAUD_MIN_PENDING_CLAIMS` | 4 | fraud_signals flags a customer_ref at this many pending claims |
| `JWT_SECRET`, `JWT_ISSUER` | local value, `mi-auth` | Must match the Auth service |
| `ROOT_PATH` | empty | `/domain` behind the gateway |
| `INTERNAL_SERVICE_TOKEN` | required | Read by `app/main.py`. Agent sends it as `X-Service-Token` on `/internal/` routes and `/evidence/resolve`. Must match the Agent service |
| `MOCK_DISPATCH_FAIL` | `false` | Demo switch: `true` makes every mock send fail with 502 `DISPATCH_FAILED` |
| `MOCK_REPLY_DELAY_SECONDS` | `5` | C-05: seconds before the mock merchant's answer shows up (0 = at once) |
| `RECHECK_MIN_DROP` | `0.5` | C-05: a recheck is `improved` when the target rate falls by at least this share (and more than the control) |

On seed 24 with `as_of` 2026-11-15 the monitor opens cases for STORE-A, STORE-B, STORE-K, STORE-L,
STORE-M, STORE-Q and STORE-R. STORE-I is `low_volume` and STORE-J (one-day spike) is `below_threshold`.

### Diagnostic rules worth knowing

- A claim belongs to the day its order was placed (store local), so a rate's numerator is always part of its denominator.
- Claims with no `item_id` are grouped as `item_id=unknown`, which has no order denominator (rate `null`).
- Claims with no `modifier_detail` are left out of modifier groups; the result's `notes` give the count.
- `evidence_ids` follow the order in agent-graph.md and stop at 200.

## Decisions, mock dispatch and audit (C-03)

### Endpoints in C-03

| Method and path | Who | Notes |
| --- | --- | --- |
| `POST /internal/cases/{case_id}/proposals` | agent | Creates `pending` version 1. 409 `PROPOSAL_PENDING`, 422 `INVALID_EVIDENCE` / `UNKNOWN_ACTION` |
| `PUT /internal/cases/{case_id}/investigation` | agent | Reports `investigation_status`; Domain sets `case_status` |
| `GET /proposals/{proposal_id}` | any user | Current version and, once approved, the dispatch |
| `POST /proposals/{proposal_id}/versions` | analyst | Edit while pending: adds the next version (201). Same text adds nothing (200) |
| `POST /proposals/{proposal_id}/decision` | analyst | `{"version", "decision", "note"}` + `Idempotency-Key`. 409 `STALE_VERSION` / `ALREADY_DECIDED`, 502 `DISPATCH_FAILED` |
| `GET /cases/{case_id}/audit` | any user | Every action on the case, oldest first |
| `GET /cases/{case_id}/rechecks` | any user | Planned and finished rechecks |
| `GET /catalog/actions` | any user | The action catalog |

### Rules

- One pending proposal per case. An edit adds a version and keeps the old ones (`proposal_versions`).
- A decision must name the current version, otherwise 409 `STALE_VERSION`.
- Approve, in one transaction: decision, mock dispatch (`dispatches`, one per proposal), case status,
  audit rows, and for an intervention or handoff a `scheduled` recheck.
- Reject: decision, case status, audit. Never a dispatch.
- Retries: the same `Idempotency-Key` returns the stored result. The same decision with a new key
  returns the existing proposal. A double click can't dispatch twice (row lock + unique `proposal_id`).
- Mock send failure: everything is rolled back except a `dispatch.failed` audit row; the proposal stays pending.
- Other stores: a GET of their case or proposal returns 404; a write (edit, decision) returns 403 `STORE_NOT_PERMITTED`.
- Internal routes (`/internal/...`) are agent only. `app/access.py` checks: a valid `X-Service-Token`
  (else 403 `SERVICE_TOKEN_INVALID`), an analyst user JWT, `X-Investigation-ID`, and `X-Store-ID` equal to
  the case's store and inside the JWT's stores (else 403 `STORE_NOT_PERMITTED`).
- 409 `PROPOSAL_PENDING` carries the pending `proposal_id` in `details`.
- Catalog IDs match the agent's fixture; `analyst_review` applies to every cause.

| Event | `case_status` |
| --- | --- |
| Proposal created | `awaiting_decision` |
| Question approved / rejected | `awaiting_merchant` / `investigating` |
| Action approved / rejected | `action_dispatched` / `analyst_review` |
| Investigation `running` / `unsure` / `failed` | `investigating` / `analyst_review` / `open` + `last_error` |

The recheck's `before` window is the target's rate over the last `recheck_after_days` days of the case
window (store local). `scheduled_for` is the dispatch time plus `recheck_after_days`.

Audit actions: `case.opened`, `proposal.created`, `proposal.edited`, `proposal.approved`,
`proposal.rejected`, `dispatch.sent`, `dispatch.failed`, `recheck.scheduled`, `investigation.<status>`.
Actors are a user ID, `svc_agent`, `svc_monitor` or (C-05) `svc_mock_merchant`.

## Merchant replies and rechecks (C-05)

### Endpoints in C-05

| Method and path | Who | Notes |
| --- | --- | --- |
| `GET /cases/{case_id}/merchant-replies` | any user, agent | Replies to the case's questions, oldest first. `text` is untrusted merchant text |
| `POST /proposals/{proposal_id}/merchant-reply` | analyst | `{"outcome": "no_reply", "text": null}` + `Idempotency-Key`. 409 `NOT_DISPATCHED` / `REPLY_EXISTS` |
| `POST /rechecks/{recheck_id}/run` | analyst | Manual demo trigger + `Idempotency-Key`. 409 `RECHECK_ALREADY_RUN` |
| `POST /cases/{case_id}/close` | analyst | "Mark as resolved": `analyst_review` → `closed`, audit `case.closed`, + `Idempotency-Key`. Any other status: 409 `CASE_NOT_CLOSABLE` |

### Merchant replies

- The merchant's answer comes in by itself. When a question is approved and dispatched, the mock
  merchant answers in the same transaction, from the seeded `mock_merchant_inbox` (`recorded_by`
  `svc_mock_merchant`). The analyst never types it.
- The answer arrives `MOCK_REPLY_DELAY_SECONDS` later (default 5): until then it isn't returned by
  `GET /cases/{id}/merchant-replies` or the evidence routes, so the run pauses on `awaiting_merchant`
  and the analyst sees the reply come in and confirms it. `recorded_at` is the arrival time. Set it to
  `0` for an instant reply (the tests do). A `no_reply` recorded before the answer arrives replaces it.
- STORE-Q's merchant answers. STORE-K's and STORE-R's never do: the analyst records `no_reply`
  (STORE-R is W-01, the store where the agent has a reason to ask).
- A reply is evidence (`EV-RPL-...`): `GET /evidence/{id}` and `POST /evidence/resolve` accept it.
- One reply per question. The case stays `awaiting_merchant` until the agent resumes and reports `running`.

### Rechecks

The data ends on Nov 15, so the "after" period is a seeded **future snapshot** (Nov 16 - Dec 13) in
`future_orders`, `future_order_items` and `future_claims`. Only a recheck reads these tables. The monitor,
the diagnostics and the agent never do, so for them the data still ends on Nov 15.

| Field | Meaning |
| --- | --- |
| `before` | The target's rate over the last `recheck_after_days` days of data (saved at approval) |
| `after` | The same target over a window of the same length after the data ends. A second recheck (after a reopen) uses the days after the first one's window |
| `control` | The store's other orders in the after window (the unaffected comparison). `null` when the target is the whole store |
| `data_sufficient` | Both windows have at least `MIN_GROUP_ORDERS` (30) target orders |

| Result | Rule | `case_status` |
| --- | --- | --- |
| `insufficient_data` | Not enough orders | `paused` |
| `improved` | After at most half of before (`RECHECK_MIN_DROP` 0.5), and a bigger drop than the control | `closed` |
| `not_improved` | Otherwise, first time | `reopened`, `reopen_count` 1 |
| `not_improved` | Otherwise, second time | `analyst_review` |

The future is scripted per store, so every result can be shown:

| Store | Weeks 1-2 (first recheck) | Weeks 3-4 (second recheck) |
| --- | --- | --- |
| STORE-A | Fixed: improved, closed | |
| STORE-B | Cause still there: not improved, reopened | Fixed: improved, closed |
| STORE-K | Reduced hours: insufficient data, paused | |
| STORE-L | Not improved, reopened | Not improved, analyst_review |
| STORE-M | Fraud ring stops: improved, closed | |

Audit actions: `merchant_reply.recorded`, `recheck.improved`, `recheck.not_improved`,
`recheck.insufficient_data` (details hold the windows and the control's before rate).

## Seeded scenarios

| Store | Role | What the data shows |
| --- | --- | --- |
| STORE-A | POS modifier | From Oct 30, "Extra sauce" orders get incorrect_item / ingredient_error claims with `modifier_detail = Extra sauce` |
| STORE-B | Dinner packing | From Nov 3, large dinner orders (5+ items) get missing_item claims; comments say a whole bag was missing |
| STORE-C to H | Normal | Claims around 1.0-1.5% of delivered orders |
| STORE-I | Low volume | High rate but only ~30 orders a week; should not open a case |
| STORE-J | One-day spike | 6 claims on Nov 8 only; 7-day rate stays normal |
| STORE-K to M | C-04 dev scenarios | See "Golden dataset" below |
| STORE-Q, R | Merchant question | See "Golden dataset" below |

Distractors: STORE-A has an Oct 20 downtime, Oct 24-26 out-of-stock cancellations, a same-day unrelated
menu change and fraud-labeled claims. STORE-B has a Nov 1 dessert price change, a Nov 3-9 promotion,
Friday dinner `too_busy` cancellations across the whole period and fraud-labeled claims.

## Golden dataset (C-04)

The answer key lives in schema `eval`, which only the `eval_runner` role can read. B-05's runner compares
the agent's results with it (contracts.md, "Golden Dataset labels").

**`eval.golden_scenarios`**: one row per data scenario. `key_evidence_ids` lists the evidence IDs behind
the true cause (the cause event plus every claim and cancellation the scenario added), so the runner can
check that the agent's cited IDs point at the real signal.

| ID | Split | Store | Situation | Label (cause / owner / action) |
| --- | --- | --- | --- | --- |
| GS-01 | dev | STORE-A | POS modifier "Extra sauce" | pos_modifier_mapping / pos_team / fix_modifier_mapping |
| GS-02 | dev | STORE-B | Large dinner orders lose a bag | packing / merchant / add_large_order_bag_check |
| GS-03 | dev | STORE-I | Low volume | no_case |
| GS-04 | dev | STORE-J | One-day spike | no_case |
| GS-05 | dev | STORE-K | From Nov 4 one taco item goes missing; out-of-stock cancellations rise; a same-day price change is a distractor | inventory / merchant / update_item_availability |
| GS-06 | dev | STORE-L | From Nov 2 wrong_order claims across all items, longer deliveries, Dasher comments; a same-day menu change is a distractor | dasher_handoff / dasher_ops / review_dasher_handoff |
| GS-07 | dev | STORE-M | From Nov 6 four customers file 7 pending "entire order" claims each; a POS update the day before is a distractor | fraud_cluster / fraud_review / send_to_fraud_review |
| GS-11 | dev | STORE-Q | From Nov 5 claims follow a new paid modifier "Add chili crisp", at dinner and late night only; a POS update the day before is a distractor. Only the merchant knows if it prints on the ticket; the merchant replies (new evening cooks miss it) | menu_change / menu_team / review_menu_change |
| GS-12 | dev | STORE-R | Same as GS-11, but the merchant never replies (W-01): a less certain diagnosis, or unsure | menu_change / menu_team / review_menu_change |
| GS-08..10 | holdout | N, O, P | Kept out of the repository until the final run | |

Holdout stores are built only with `--holdout`, from `scripts/holdout_stores.py`, which is not committed:

```bash
python -m domain.scripts.reset_and_seed            # dev: 15 stores, 9 golden scenarios
python -m domain.scripts.reset_and_seed --holdout  # final run: 18 stores, 12 golden scenarios
```

Each scenario store has its own random seed and is generated after the C-01 stores, so STORE-A..J and
every dev ID (orders, claims, events, `key_evidence_ids`) are the same with or without `--holdout`.

**`eval.workflow_scenarios`**: what the system must do, not what the agent concludes. Each row has
`steps` and an `expected` list of checks (`status`, `code`, `case_status`, `dispatches`, ...).

| ID | Scenario | Runs in |
| --- | --- | --- |
| W-01 | No merchant reply (STORE-R) | `tests/test_workflow_scenarios.py`; the agent part in B-05 |
| W-02 | Failed recheck, reopen once, then analyst handoff (STORE-L) | `tests/test_workflow_scenarios.py` |
| W-03 | Invalid or incomplete input | `tests/test_workflow_scenarios.py` |
| W-04 | Unauthorized or cross-store access | `tests/test_workflow_scenarios.py` |
| W-05 | Attempted dispatch without approval | `tests/test_workflow_scenarios.py` |

## Conventions

- IDs: `STORE-A`, `ITEM-A-007`, `ORD-000123`, `EV-CLM-000123` (claim), `EV-CXL-000045` (cancellation),
  `EV-EVT-000010` (operational event), `CASE-0001`, `GS-01`.
- Timestamps are stored in UTC. `daypart` is the meal period by the store's local order time
  (breakfast 05-10, lunch 11-15, dinner 16-20, late_night 21-04), not a staff shift.
- Store-attributable M&I rate = claims not disqualified (excluding `fraud` and `not_store_fault`;
  `pending` still counts) / delivered orders in the window, as the sprint plan's monitor rule says.
- `orders.customer_ref` is a synthetic customer ID (for fraud-cluster checks); `cancellations.item_id`
  names the out-of-stock item when known.
- `eval.golden_scenarios` is the answer key. Domain APIs and agent tools must never read it.
- All data is synthetic. No real personal data.

# Domain service (C-01 data, C-02 APIs)

SQLAlchemy models, seed data for 10 stores (Oct 5 - Nov 15, 2026), and the Domain API:
cases, store data, read-only diagnostic tools and the fixed-rule store monitor.

## Files

| Path | What it is |
| --- | --- |
| `app/db.py` | Engine and session. Reads `DATABASE_URL`, or the `POSTGRES_*` variables from docker compose |
| `app/models.py` | 10 tables: 9 in schema `domain` (incl. `idempotency_keys`), answer key in schema `eval` |
| `alembic.ini`, `migrations/` | Alembic migrations; the version table lives in schema `domain` |
| `scripts/reset_and_seed.py` | Drops both schemas, runs `alembic upgrade head`, then loads seed data (fixed seed 24) |
| `scripts/check_seed.py` | Row counts, integrity checks and M&I rate per store |
| `scripts/make_demo_token.py` | Prints a local JWT for `/docs` demos and manual testing |
| `app/main.py` | FastAPI app: `/health`, `/ready` and the routers below |
| `app/settings.py` | Environment variables (monitor thresholds, JWT) |
| `app/security.py`, `app/errors.py` | JWT check, store scoping, one error envelope |
| `app/routers/` | `cases`, `stores` (store, menu, overview, diagnostics), `monitor`, `evidence` |
| `app/services/` | The logic: data loading, diagnostics, monitor, cases, evidence |
| `tests/` | pytest suite that runs against the seeded database |

## Run it

1. Start PostgreSQL (skip if the project's docker compose already runs it):

   ```bash
   docker run --name retail-pg -e POSTGRES_PASSWORD=postgres -e POSTGRES_DB=retail -p 5432:5432 -d postgres:16
   ```

2. Install dependencies and point to the database (Git Bash on Windows):

   ```bash
   python -m venv .venv
   source .venv/Scripts/activate      # macOS/Linux: source .venv/bin/activate
   pip install -r requirements.txt
   export DATABASE_URL="postgresql+psycopg://postgres:postgres@localhost:5432/retail"
   ```

3. Create or upgrade the tables with the migration identity:

   ```bash
   alembic upgrade head
   ```

4. Reset and seed demo data, then check:

   ```bash
   python -m scripts.reset_and_seed
   python -m scripts.check_seed
   ```

   Running the reset again deletes everything in `domain` and `eval` and produces identical data.

## Run the API (C-02)

```bash
export JWT_SECRET="change-me-32-bytes-min-local-only"   # must match the Auth service
uvicorn app.main:app --reload --port 8003
```

Open http://localhost:8003/docs. Every route except `/health` and `/ready` needs
`Authorization: Bearer <jwt>` from the Auth service (HS256, claims `sub`, `role`, `store_ids`, `iss`).

For a local demo without the Auth service, print a token signed with the same `JWT_SECRET`, then paste it
into the **Authorize** button on `/docs`:

```bash
python -m scripts.make_demo_token            # loe_analyst, all 10 stores, valid 12 hours
```

Run the tests (they need the seeded database and clear `domain.cases` between tests):

```bash
python -m scripts.reset_and_seed
python -m pytest -q tests
```

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
| `GET /evidence/{evidence_id}`, `POST /evidence/resolve` | any user | Evidence lookup and checking cited IDs |

Without `start`/`end`, a tool uses the 42 days ending on the store's last day of data.
Audit, merchant replies, rechecks, proposals, the action catalog and `/internal/` routes come in C-03 and C-04.

### Monitor rule

For each store in the caller's grants, with `as_of` as the last day (default: the last day of data):

- Window: the 7 days ending on `as_of`. Baseline: the 28 days before the window. Dates are store local.
- Rate = store-attributable claims (`store_fault` + `pending`) / delivered orders.
- Skipped when the store already has a case that is not `closed` (`open_case_exists`) or the window
  has fewer than `MONITOR_MIN_ORDERS` delivered orders (`low_volume`).
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

On seed 24 with `as_of` 2026-11-15 the monitor opens cases for STORE-A and STORE-B only. STORE-I is
`low_volume` and STORE-J (one-day spike) is `below_threshold`.

### Diagnostic rules worth knowing

- A claim belongs to the day its order was placed (store local), so a rate's numerator is always part of its denominator.
- Claims with no `item_id` are grouped as `item_id=unknown`, which has no order denominator (rate `null`).
- Claims with no `modifier_detail` are left out of modifier groups; the result's `notes` give the count.
- `evidence_ids` follow the order in agent-graph.md and stop at 200.

## Changing a table

When using the shared A-01 database, run migrations and seed commands as
`db_migrator`, with `DATABASE_URL` set to that role's connection URL and
`PGPASSWORD` set from `MIGRATION_DB_PASSWORD`. After the intentional reset command
recreates `domain` and `eval`, run `docker compose run --rm db-setup` from
`a-01-scaffold` to restore runtime grants. The Domain API uses `domain_svc`.
The B-05 evaluation runner uses the separate read-only `eval_runner` identity.

1. Edit the model in `app/models.py`.
2. `alembic revision --autogenerate -m "describe the change"` and review the new file in `migrations/versions/`.
3. `alembic upgrade head`, then commit the model change and the migration together.

## Seeded scenarios

| Store | Role | What the data shows |
| --- | --- | --- |
| STORE-A | POS modifier | From Oct 30, "Extra sauce" orders get incorrect_item / ingredient_error claims with `modifier_detail = Extra sauce` |
| STORE-B | Dinner packing | From Nov 3, large dinner orders (5+ items) get missing_item claims; comments say a whole bag was missing |
| STORE-C to H | Normal | Claims around 1.0-1.5% of delivered orders |
| STORE-I | Low volume | High rate but only ~30 orders a week; should not open a case |
| STORE-J | One-day spike | 6 claims on Nov 8 only; 7-day rate stays normal |

Distractors: STORE-A has an Oct 20 downtime, Oct 24-26 out-of-stock cancellations, a same-day unrelated
menu change and fraud-labeled claims. STORE-B has a Nov 1 dessert price change, a Nov 3-9 promotion,
Friday dinner `too_busy` cancellations across the whole period and fraud-labeled claims.

Pending claims (review not finished): store_fault claims reported in the last 36 hours of data are
`pending`, and one STORE-A customer_ref files 5 pending "entire order" claims from Nov 6 to 15, so
`fraud_signals` flags it. These use their own random generator, so the other seeded rows stay the same,
but claim evidence IDs shift because IDs are assigned in time order.

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

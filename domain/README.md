# Domain Service

FastAPI service with JWT/store access control, SQLAlchemy models, migrations and
repeatable synthetic data for 10 stores (Oct 5 - Nov 15, 2026). The entry point is
`domain.app.main:app`; Compose builds this directory together with `shared/`.
Run all commands below in Bash on macOS from the repository root.

## Files

| Path | What it is |
| --- | --- |
| `app/main.py`, `app/access.py` | API entry point, health/readiness, store/menu reads and default-deny authorization |
| `app/db.py` | Administrative engine/session using the same shared configuration as the API |
| `app/models.py` | 9 tables: 8 in schema `domain`, answer key in schema `eval` |
| `alembic.ini`, `migrations/` | Alembic migrations; the version table lives in schema `domain` |
| `scripts/reset_and_seed.py` | Drops both schemas, runs `alembic upgrade head`, then loads seed data (fixed seed 24) |
| `scripts/check_seed.py` | Row counts, integrity checks and M&I rate per store |

## Run the API

```bash
docker compose up --build domain
```

Compose uses `domain_svc`, restricted to the `domain` schema. Auth/Agent share
the JWT verification code in `shared/`; Domain independently verifies forwarded
tokens and resolves case/proposal ownership before authorizing a request.
The existing C-02/C-03 business handlers remain separate implementation work.

Direct development uses `uvicorn domain.app.main:app --root-path /domain` from the repository root
with `JWT_SECRET`, `INTERNAL_SERVICE_TOKEN` and the Domain database environment
configured. The root `.env` is loaded by Compose, not automatically by Python.

## Migrate and seed

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

# Domain DB: models and seed data (C-01)

SQLAlchemy models for the Domain service plus a repeatable script that resets
PostgreSQL and loads synthetic data for 10 stores (Oct 5 - Nov 15, 2026).

## Files

| Path | What it is |
| --- | --- |
| `app/db.py` | Engine and session, reads `DATABASE_URL` |
| `app/models.py` | 9 tables: 8 in schema `domain`, answer key in schema `eval` |
| `alembic.ini`, `migrations/` | Alembic migrations; the version table lives in schema `domain` |
| `scripts/reset_and_seed.py` | Drops both schemas, runs `alembic upgrade head`, then loads seed data (fixed seed 24) |
| `scripts/check_seed.py` | Row counts, integrity checks and M&I rate per store |

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

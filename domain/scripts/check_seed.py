"""Sanity checks for the seeded Domain database (C-01 acceptance criteria).

Usage (from the repository root):
    python -m domain.scripts.check_seed
"""
from sqlalchemy import text

from domain.app.db import engine

CHECKS = {
    "claims without a valid order": """
        SELECT count(*) FROM domain.mi_claims c
        LEFT JOIN domain.orders o ON o.order_id = c.order_id
        WHERE o.order_id IS NULL OR o.store_id <> c.store_id""",
    "claims missing evidence id, timestamps or label": """
        SELECT count(*) FROM domain.mi_claims
        WHERE evidence_id IS NULL OR reported_at IS NULL OR review_label IS NULL
           OR (review_label <> 'pending' AND reviewed_at IS NULL)
           OR (review_label = 'pending' AND reviewed_at IS NOT NULL)""",
    "claims on canceled orders": """
        SELECT count(*) FROM domain.mi_claims c JOIN domain.orders o USING (order_id)
        WHERE o.status = 'canceled'""",
    "claims reported before delivery": """
        SELECT count(*) FROM domain.mi_claims c JOIN domain.orders o USING (order_id)
        WHERE c.reported_at < o.delivered_at""",
}

# 7-day window Nov 9-15 vs 28-day baseline Oct 12 - Nov 8 (UTC dates, good enough for a check)
RATES = """
WITH o AS (
  SELECT store_id,
         count(*) FILTER (WHERE placed_at >= '2026-11-09' AND placed_at < '2026-11-16') AS orders_7d,
         count(*) FILTER (WHERE placed_at >= '2026-10-12' AND placed_at < '2026-11-09') AS orders_28d
  FROM domain.orders WHERE status = 'delivered' GROUP BY store_id),
c AS (
  SELECT c.store_id,
         count(*) FILTER (WHERE o.placed_at >= '2026-11-09' AND o.placed_at < '2026-11-16') AS claims_7d,
         count(*) FILTER (WHERE o.placed_at >= '2026-10-12' AND o.placed_at < '2026-11-09') AS claims_28d
  FROM domain.mi_claims c JOIN domain.orders o USING (order_id)
  WHERE c.review_label NOT IN ('fraud', 'not_store_fault')  -- disqualified claims
  GROUP BY c.store_id)
SELECT o.store_id, o.orders_7d, coalesce(c.claims_7d, 0) AS claims_7d,
       round(100.0 * coalesce(c.claims_7d, 0) / nullif(o.orders_7d, 0), 2) AS rate_7d_pct,
       round(100.0 * coalesce(c.claims_28d, 0) / nullif(o.orders_28d, 0), 2) AS baseline_28d_pct
FROM o LEFT JOIN c USING (store_id) ORDER BY o.store_id
"""


def main() -> None:
    with engine.connect() as conn:
        print("Row counts")
        for t in ["stores", "menu_items", "orders", "order_items", "mi_claims",
                  "cancellations", "operational_events", "cases"]:
            print(f"  domain.{t:<20} {conn.execute(text(f'SELECT count(*) FROM domain.{t}')).scalar()}")
        print(f"  eval.golden_scenarios      {conn.execute(text('SELECT count(*) FROM eval.golden_scenarios')).scalar()}")

        print("\nIntegrity checks (all should be 0)")
        ok = True
        for name, sql in CHECKS.items():
            n = conn.execute(text(sql)).scalar()
            ok &= n == 0
            print(f"  {'OK ' if n == 0 else 'BAD'} {name}: {n}")

        print("\nStore-attributable M&I rate (excl. fraud / not_store_fault): last 7 days vs 28-day baseline")
        print(f"  {'store':<8} {'orders_7d':>9} {'claims_7d':>9} {'rate_7d%':>8} {'base_28d%':>9}")
        for row in conn.execute(text(RATES)):
            print(f"  {row.store_id:<8} {row.orders_7d:>9} {row.claims_7d:>9} "
                  f"{row.rate_7d_pct or 0:>8} {row.baseline_28d_pct or 0:>9}")

        print("\nAll integrity checks passed." if ok else "\nSome checks FAILED.")


if __name__ == "__main__":
    main()

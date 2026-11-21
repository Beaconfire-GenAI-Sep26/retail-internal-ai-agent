"""Future snapshot and mock merchant answers (C-05).

Rechecks compare a target's claim rate before and after an approved action. The seed data ends on
Nov 15, so the "after" period has to be seeded too. This module writes 4 weeks after the last day of
data (Nov 16 - Dec 13) into separate tables (`future_orders`, `future_order_items`, `future_claims`).

- Only `POST /rechecks/{id}/run` reads them. The monitor, the diagnostics and the agent never do, so
  for them the data still ends on Nov 15 and nothing from C-01..C-04 moves.
- The future is scripted per store: whether the store's real cause is still there in weeks 1-2
  (first recheck) and weeks 3-4 (second recheck, after a reopen). That covers every recheck outcome:

    store    weeks 1-2                         weeks 3-4                 demo path
    STORE-A  fixed                             fixed                     improved -> closed
    STORE-B  cause still there                 fixed                     not improved -> reopened,
                                                                         then improved -> closed
    STORE-K  reduced hours (about 3 orders/day) fixed                    insufficient data -> paused
    STORE-L  cause still there                 cause still there         not improved twice -> analyst_review
    STORE-M  the fraud ring stops              stops                     improved -> closed

  Other stores get no future data, so a recheck there reports insufficient data.
- Generated last, with its own random generator and its own IDs (FUT-ORD-, FUT-CLM-), so every
  other row and ID is the same as before C-05.

`MERCHANT_INBOX` is what each store's mock merchant answers when a question is dispatched to it.
STORE-K has no entry: it never answers, so an analyst records no_reply (workflow scenario W-01).
"""
import random
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from typing import Callable
from zoneinfo import ZoneInfo

from domain.app.models import (
    Daypart,
    ErrorCategory,
    FutureClaim,
    FutureOrder,
    FutureOrderItem,
    MenuItem,
    ReviewLabel,
)
from domain.scripts.scenario_stores import daypart_for, open_hours

FUTURE_SEED = 24 + 4  # SEED + 4; +2 and +3 are the C-04 dev and holdout stores
FUTURE_START = date(2026, 11, 16)  # the day after the last day of data
FUTURE_DAYS = 28
BLOCK_DAYS = 14  # weeks 1-2 = block 0 (first recheck), weeks 3-4 = block 1 (second recheck)

MERCHANT_INBOX = {
    "STORE-A": "We added Extra sauce as a paid option at the end of October. I'm not sure the kitchen "
               "printer shows it; the cooks say they follow the ticket.",
    "STORE-B": "Since early November our big dinner orders go out in two bags. When it's busy the second "
               "bag sometimes stays on the pickup shelf.",
    "STORE-L": "We moved the pickup shelf next to the dine-in counter on Nov 2. Dashers sometimes take a "
               "bag from the wrong shelf.",
    "STORE-M": "Nothing changed on our side. Every order is handed to the Dasher and our photos show the "
               "bags being picked up.",
}


@dataclass
class FutureSpec:
    per_day: tuple  # orders per day in block 0 and block 1
    modifier_rate: dict = field(default_factory=dict)  # modifier -> probability a line takes it (else 0.15)
    cause: Callable = None  # (order dict, block, rng) -> list of claim tuples, or []


def _label(rng, store_fault=0.88, fraud=0.02) -> ReviewLabel:
    r = rng.random()
    if r < fraud:
        return ReviewLabel.FRAUD
    if r < fraud + store_fault:
        return ReviewLabel.STORE_FAULT
    return ReviewLabel.NOT_STORE_FAULT


def _b_bag(o, block, rng):
    """STORE-B: the bag problem goes on in weeks 1-2 (the first fix didn't stick), fixed in weeks 3-4."""
    if block == 0 and o["daypart"] == Daypart.DINNER and o["item_count"] >= 5 and rng.random() < 0.35:
        bag = [m for m, _ in o["lines"] if m.category in ("drink", "dessert", "side")] or [o["lines"][-1][0]]
        return [(ErrorCategory.MISSING_ITEM, m, None, _label(rng)) for m in bag[: rng.randint(1, 3)]]
    return []


def _l_handoff(o, block, rng):
    """STORE-L: Dashers keep taking the wrong bag in both blocks."""
    if rng.random() < 0.08:
        label = rng.choices([ReviewLabel.STORE_FAULT, ReviewLabel.NOT_STORE_FAULT, ReviewLabel.PENDING],
                            [60, 30, 10])[0]
        return [(ErrorCategory.WRONG_ORDER, None, None, label)]
    return []


FUTURE_SPECS = {
    "STORE-A": FutureSpec(per_day=(60, 60), modifier_rate={"Extra sauce": 0.40}),  # mapping fixed
    "STORE-B": FutureSpec(per_day=(70, 70), cause=_b_bag),
    "STORE-K": FutureSpec(per_day=(3, 65)),  # kitchen remodel: reduced hours in weeks 1-2
    "STORE-L": FutureSpec(per_day=(70, 70), cause=_l_handoff),
    "STORE-M": FutureSpec(per_day=(60, 60)),  # the four customer_refs stop ordering
}


@dataclass
class FutureRows:
    orders: list = field(default_factory=list)
    order_items: list = field(default_factory=list)
    claims: list = field(default_factory=list)


def build_future(stores: list, menus: dict[str, list[MenuItem]], hour_weights: dict,
                 base_claim_rate: float) -> FutureRows:
    """Rows for FUTURE_SPECS stores. `stores` and `menus` are the rows reset_and_seed just built."""
    rng = random.Random(FUTURE_SEED)
    by_id = {s.store_id: s for s in stores}
    out = FutureRows()
    n_order = n_claim = 0
    for sid, spec in FUTURE_SPECS.items():
        store, items = by_id[sid], menus[sid]
        zone = ZoneInfo(store.timezone)
        o_s, c_s = store.opening_hours["open"], store.opening_hours["close"]
        hours = open_hours(o_s, c_s)
        weights = [hour_weights.get(h, 1) for h in hours]
        entrees = [m for m in items if m.category == "entree"]
        others = [m for m in items if m.category != "entree"]
        for offset in range(FUTURE_DAYS):
            d = FUTURE_START + timedelta(days=offset)
            block = offset // BLOCK_DAYS
            n = spec.per_day[block] * (1.2 if d.weekday() in (4, 5) else 1.0)
            n = max(0, round(rng.gauss(n, max(1.0, n * 0.12))))
            for _ in range(n):
                hour = rng.choices(hours, weights)[0]
                day = d if hour >= int(o_s[:2]) else d + timedelta(days=1)
                dp = daypart_for(hour)
                n_lines = rng.choices([1, 2, 3, 4, 5], [25, 30, 25, 12, 8] if dp == Daypart.DINNER
                                      else [40, 32, 18, 7, 3])[0]
                lines = []
                for li in range(n_lines):
                    m = rng.choice(entrees) if li == 0 or rng.random() < 0.35 else rng.choice(others)
                    mods = [mod for mod in m.available_modifiers
                            if rng.random() < spec.modifier_rate.get(mod, 0.15)]
                    lines.append((m, mods))
                n_order += 1
                oid = f"FUT-ORD-{n_order:06d}"
                o = dict(daypart=dp, item_count=n_lines, lines=lines)
                out.orders.append(FutureOrder(
                    order_id=oid, store_id=sid, daypart=dp, item_count=n_lines,
                    placed_at=datetime.combine(day, time(hour, rng.randint(0, 59)), zone).astimezone(ZoneInfo("UTC")),
                ))
                out.order_items += [FutureOrderItem(order_id=oid, item_id=m.item_id, modifiers=mods)
                                    for m, mods in lines]

                new = spec.cause(o, block, rng) if spec.cause else []
                if not new and rng.random() < base_claim_rate:  # the normal background rate
                    cat = rng.choices(list(ErrorCategory), [45, 25, 20, 10])[0]
                    m, mods = rng.choice(lines)
                    if cat == ErrorCategory.WRONG_ORDER:
                        new = [(cat, None, None, _label(rng, 0.75, 0.08))]
                    else:
                        mod = rng.choice(mods) if (mods and cat == ErrorCategory.INGREDIENT_ERROR) else None
                        new = [(cat, m, mod, _label(rng, 0.75, 0.08))]
                for cat, m, mod, label in new:
                    n_claim += 1
                    out.claims.append(FutureClaim(
                        claim_id=f"FUT-CLM-{n_claim:06d}", order_id=oid, store_id=sid,
                        item_id=m.item_id if m else None, error_category=cat, modifier_detail=mod,
                        review_label=label,
                    ))
    return out


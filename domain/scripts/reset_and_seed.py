"""Reset the Domain database and load synthetic seed data (C-01).

Usage (from the folder that contains `app/`):
    python -m scripts.reset_and_seed

What it does
1. Drops the `domain` and `eval` schemas (ALL DATA IS DELETED).
2. Rebuilds every table by running the Alembic migrations (alembic upgrade head).
3. Generates ~6 weeks of synthetic orders for 10 stores (Oct 5 - Nov 15, 2026)
   with a fixed random seed (SEED), so every run produces identical data.

Scenarios
- STORE-A  POS modifier: from Oct 30 the "Extra sauce" modifier is not mapped
           to the kitchen ticket -> incorrect_item / ingredient_error claims.
- STORE-B  Dinner packing: from Nov 3 large dinner orders lose a whole bag
           -> missing_item claims on drinks / desserts / sides.
- STORE-C..H normal stores, STORE-I low volume, STORE-J one-day spike.
All names, comments and numbers are synthetic. No real personal data.
"""
import random
from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import text

from app.db import SessionLocal, engine
from app.models import (
    DOMAIN_SCHEMA,
    EVAL_SCHEMA,
    Cancellation,
    CancellationCategory,
    Daypart,
    ErrorCategory,
    EventType,
    GoldenScenario,
    MenuItem,
    MIClaim,
    OperationalEvent,
    Order,
    OrderItem,
    OrderStatus,
    ReviewLabel,
    Store,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SEED = 24
START_DATE = date(2026, 10, 5)
END_DATE = date(2026, 11, 15)  # inclusive
UTC = timezone.utc

A_CAUSE_DATE = date(2026, 10, 30)  # Extra sauce modifier added, not mapped to kitchen ticket
B_CAUSE_DATE = date(2026, 11, 3)  # dinner-daypart packing problem starts
B_PROMO = (date(2026, 11, 3), date(2026, 11, 9))
J_SPIKE_DATE = date(2026, 11, 8)
# Pending claims (review not finished). Added in C-02 so fraud_signals has data to find.
# They use their own random generator, so every other seeded row stays exactly as before.
PENDING_SEED = SEED + 1
REVIEW_BACKLOG_HOURS = 36  # store_fault claims reported this close to the end of data are still pending
FRAUD_CLUSTER_STORE = "STORE-A"
FRAUD_CLUSTER_CLAIMS = 5  # one customer_ref, all pending; FRAUD_MIN_PENDING_CLAIMS is 4
FRAUD_CLUSTER_DAYS = (date(2026, 11, 6), date(2026, 11, 15))  # store local dates, inclusive

BASE_CLAIM_RATE = 0.014  # normal M&I claims per delivered order
BASE_CANCEL_RATE = 0.012

rng = random.Random(SEED)

# ---------------------------------------------------------------------------
# Stores and menus
# ---------------------------------------------------------------------------
STORES = [
    # id, name, city, timezone, cuisine, open, close, orders/day
    ("STORE-A", "Golden Wok Kitchen", "Chicago", "America/Chicago", "chinese", "11:00", "22:00", 60),
    ("STORE-B", "Lone Star Family Grill", "Houston", "America/Chicago", "american", "11:00", "22:00", 70),
    ("STORE-C", "Bella Forno Pizzeria", "Chicago", "America/Chicago", "italian", "11:00", "23:00", 80),
    ("STORE-D", "Taqueria Sol", "Dallas", "America/Chicago", "mexican", "10:00", "22:00", 65),
    ("STORE-E", "Morning Bell Cafe", "Atlanta", "America/New_York", "breakfast", "06:00", "15:00", 45),
    ("STORE-F", "Sakura Ramen House", "Seattle", "America/Los_Angeles", "japanese", "11:00", "22:00", 55),
    ("STORE-G", "Green Leaf Bowls", "Denver", "America/Denver", "healthy", "10:00", "21:00", 35),
    ("STORE-H", "Midnight Burger Co", "Phoenix", "America/Phoenix", "american", "11:00", "02:00", 90),
    ("STORE-I", "Corner Dumpling Stand", "Boston", "America/New_York", "chinese", "11:00", "20:00", 4),
    ("STORE-J", "Saffron Curry House", "Newark", "America/New_York", "indian", "11:00", "22:00", 50),
]

# name, category, price, modifiers
MENUS = {
    "chinese": [
        ("Orange Chicken", "entree", 13.99, ["Extra spicy", "No onion"]),
        ("Kung Pao Chicken", "entree", 14.49, ["Extra spicy", "No peanuts"]),
        ("Beef and Broccoli", "entree", 15.99, ["No onion"]),
        ("Sweet and Sour Pork", "entree", 14.99, []),
        ("Mapo Tofu", "entree", 12.99, ["Extra spicy"]),
        ("Fried Rice", "side", 7.99, ["No egg"]),
        ("Chow Mein", "side", 8.49, []),
        ("Egg Rolls (2)", "side", 4.99, []),
        ("Hot and Sour Soup", "side", 5.49, []),
        ("Jasmine Tea", "drink", 2.99, []),
        ("Bubble Milk Tea", "drink", 5.49, ["Less sugar", "No ice"]),
        ("Mango Pudding", "dessert", 4.99, []),
    ],
    "american": [
        ("Classic Cheeseburger", "entree", 12.99, ["No pickles", "Add bacon"]),
        ("BBQ Brisket Plate", "entree", 18.99, ["Extra BBQ sauce"]),
        ("Fried Chicken (3 pc)", "entree", 14.99, ["Spicy"]),
        ("Grilled Chicken Sandwich", "entree", 12.49, ["No mayo"]),
        ("Family Meal for 4", "entree", 42.99, []),
        ("French Fries", "side", 4.49, ["Cajun seasoning"]),
        ("Mac and Cheese", "side", 5.49, []),
        ("Coleslaw", "side", 3.49, []),
        ("Onion Rings", "side", 4.99, []),
        ("Lemonade", "drink", 3.49, ["No ice"]),
        ("Iced Sweet Tea", "drink", 2.99, []),
        ("Chocolate Shake", "drink", 5.99, []),
        ("Pecan Pie Slice", "dessert", 4.99, []),
        ("Brownie", "dessert", 3.99, []),
    ],
    "italian": [
        ("Margherita Pizza", "entree", 15.99, ["Extra cheese", "Gluten-free crust"]),
        ("Pepperoni Pizza", "entree", 17.49, ["Extra cheese"]),
        ("Chicken Alfredo", "entree", 16.99, []),
        ("Spaghetti Bolognese", "entree", 15.49, []),
        ("Garlic Knots", "side", 5.99, []),
        ("Caesar Salad", "side", 8.99, ["No croutons"]),
        ("Soda Can", "drink", 1.99, []),
        ("Tiramisu", "dessert", 6.99, []),
    ],
    "mexican": [
        ("Carne Asada Tacos (3)", "entree", 12.99, ["No cilantro", "Extra salsa"]),
        ("Chicken Burrito", "entree", 11.99, ["No beans", "Add guacamole"]),
        ("Veggie Quesadilla", "entree", 10.49, []),
        ("Chips and Guacamole", "side", 6.49, []),
        ("Elote", "side", 4.99, []),
        ("Horchata", "drink", 3.99, []),
        ("Jarritos", "drink", 2.99, []),
        ("Churros", "dessert", 4.99, []),
    ],
    "breakfast": [
        ("Pancake Stack", "entree", 10.99, ["Add blueberries"]),
        ("Breakfast Burrito", "entree", 11.49, ["No onion"]),
        ("Avocado Toast", "entree", 9.99, ["Add egg"]),
        ("Hash Browns", "side", 3.99, []),
        ("Fruit Cup", "side", 4.49, []),
        ("Latte", "drink", 4.99, ["Oat milk", "Extra shot"]),
        ("Orange Juice", "drink", 3.99, []),
        ("Blueberry Muffin", "dessert", 3.49, []),
    ],
    "japanese": [
        ("Tonkotsu Ramen", "entree", 15.99, ["Extra noodles", "Spicy"]),
        ("Miso Ramen", "entree", 14.99, ["Extra noodles"]),
        ("Chicken Katsu Curry", "entree", 15.49, []),
        ("Gyoza (6)", "side", 7.49, []),
        ("Edamame", "side", 4.99, []),
        ("Ramune", "drink", 3.49, []),
        ("Matcha Ice Cream", "dessert", 4.99, []),
    ],
    "healthy": [
        ("Chicken Power Bowl", "entree", 13.49, ["No dressing", "Extra protein"]),
        ("Salmon Poke Bowl", "entree", 15.99, ["Extra avocado"]),
        ("Vegan Buddha Bowl", "entree", 12.49, []),
        ("Side Salad", "side", 4.99, []),
        ("Green Smoothie", "drink", 6.49, ["Add protein"]),
        ("Kombucha", "drink", 4.49, []),
        ("Energy Bites", "dessert", 3.99, []),
    ],
    "indian": [
        ("Chicken Tikka Masala", "entree", 16.49, ["Mild", "Extra spicy"]),
        ("Lamb Rogan Josh", "entree", 18.49, []),
        ("Chana Masala", "entree", 13.49, []),
        ("Garlic Naan", "side", 3.99, []),
        ("Basmati Rice", "side", 3.49, []),
        ("Samosas (2)", "side", 5.99, []),
        ("Mango Lassi", "drink", 4.49, []),
        ("Gulab Jamun", "dessert", 4.99, []),
    ],
}

# Hourly order weights (local hour -> weight); lunch and dinner peaks.
HOUR_WEIGHTS = {
    6: 2, 7: 4, 8: 5, 9: 5, 10: 4, 11: 8, 12: 12, 13: 10, 14: 5, 15: 4,
    16: 5, 17: 9, 18: 13, 19: 12, 20: 8, 21: 5, 22: 3, 23: 2, 0: 2, 1: 1,
}

# ---------------------------------------------------------------------------
# Comment templates
# ---------------------------------------------------------------------------
GENERIC_COMMENTS = {
    ErrorCategory.MISSING_ITEM: [
        "My {item} was not in the bag.",
        "{item} missing from the order.",
        "Never received the {item}.",
        None,
    ],
    ErrorCategory.INCORRECT_ITEM: [
        "Got the wrong item instead of {item}.",
        "Received something else, not {item}.",
        None,
    ],
    ErrorCategory.INGREDIENT_ERROR: [
        "{item} was made wrong, ingredients were off.",
        "Asked for changes on {item} but they were ignored.",
        None,
    ],
    ErrorCategory.WRONG_ORDER: [
        "This was someone else's order entirely.",
        "Whole order was wrong, none of it was mine.",
    ],
}
SAUCE_COMMENTS = [
    "Paid for extra sauce on the {item}, got none.",
    "No extra sauce at all even though I paid for it.",
    "Ordered {item} with extra sauce, came completely dry.",
    "Extra sauce was charged but missing.",
    "The {item} had no sauce, the add-on was ignored.",
    None,
]
BAG_COMMENTS = [
    "The whole second bag never arrived. No drinks, no dessert.",
    "Only got one bag, the {item} and the rest were missing.",
    "Half the order was missing, looks like a bag was left behind.",
    "Drinks and dessert bag missing.",
    "Missing the {item} and everything else that should have been in the other bag.",
    "Big family order, a whole bag was not included.",
    None,
]
FRAUD_COMMENTS = [
    "Everything was missing, refund all of it.",
    "Nothing in the bag was right. Full refund please.",
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def daterange(start: date, end: date):
    d = start
    while d <= end:
        yield d
        d += timedelta(days=1)


def daypart_for(hour: int) -> Daypart:
    if 5 <= hour <= 10:
        return Daypart.BREAKFAST
    if 11 <= hour <= 15:
        return Daypart.LUNCH
    if 16 <= hour <= 20:
        return Daypart.DINNER
    return Daypart.LATE_NIGHT


def open_hours(open_s: str, close_s: str) -> list[int]:
    o, c = int(open_s[:2]), int(close_s[:2])
    if c <= o:  # closes after midnight
        return list(range(o, 24)) + list(range(0, c))
    return list(range(o, c))


def money(x: float) -> Decimal:
    return Decimal(f"{x:.2f}")


def pick_review_label(store_fault_p: float = 0.75, fraud_p: float = 0.08) -> ReviewLabel:
    r = rng.random()
    if r < fraud_p:
        return ReviewLabel.FRAUD
    if r < fraud_p + store_fault_p:
        return ReviewLabel.STORE_FAULT
    return ReviewLabel.NOT_STORE_FAULT


def fmt_comment(templates: list, item_name: str) -> str | None:
    t = rng.choice(templates)
    return t.format(item=item_name) if t else None


# ---------------------------------------------------------------------------
# Main generation
# ---------------------------------------------------------------------------
def reset_schema() -> None:
    """Drop this service's schemas (data + Alembic version table) and rebuild
    the tables by running every Alembic migration from scratch."""
    with engine.begin() as conn:
        for schema in (DOMAIN_SCHEMA, EVAL_SCHEMA):
            conn.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
    alembic_cfg = Config(str(PROJECT_ROOT / "alembic.ini"))
    command.upgrade(alembic_cfg, "head")


def build_stores_and_menus():
    stores, menus = [], {}
    for sid, name, city, tz, cuisine, o, c, _ in STORES:
        stores.append(
            Store(
                store_id=sid, name=name, city=city, timezone=tz, cuisine=cuisine,
                opening_hours={"open": o, "close": c}, is_active=True,
                onboarded_at=datetime(2024, rng.randint(1, 12), rng.randint(1, 28), tzinfo=UTC),
            )
        )
        letter = sid.split("-")[1]
        items = []
        for i, (iname, cat, price, mods) in enumerate(MENUS[cuisine], start=1):
            mods = list(mods)
            if sid == "STORE-A" and cat == "entree":
                mods.append("Extra sauce")  # added Oct 30 (see operational_events)
            items.append(
                MenuItem(
                    item_id=f"ITEM-{letter}-{i:03d}", store_id=sid, name=iname, category=cat,
                    price=money(price), available_modifiers=mods,
                )
            )
        menus[sid] = items
    return stores, menus


def generate_orders(menus):
    """Return a list of raw order dicts (IDs assigned later in time order)."""
    raw = []
    for sid, _, _, tz, _, o, c, per_day in STORES:
        zone = ZoneInfo(tz)
        hours = open_hours(o, c)
        weights = [HOUR_WEIGHTS.get(h, 1) for h in hours]
        menu = menus[sid]
        entrees = [m for m in menu if m.category == "entree"]
        others = [m for m in menu if m.category != "entree"]
        for d in daterange(START_DATE, END_DATE):
            n = per_day * (1.2 if d.weekday() in (4, 5) else 1.0)
            if sid == "STORE-B" and B_PROMO[0] <= d <= B_PROMO[1]:
                n *= 1.25
            n = max(0, round(rng.gauss(n, max(1.0, n * 0.12))))
            for _ in range(n):
                hour = rng.choices(hours, weights)[0]
                local_day = d if hour >= int(o[:2]) else d + timedelta(days=1)
                local_dt = datetime.combine(local_day, time(hour, rng.randint(0, 59)), zone)
                dp = daypart_for(hour)
                # Dinner orders are larger (family orders)
                n_lines = rng.choices([1, 2, 3, 4, 5], [25, 30, 25, 12, 8] if dp == Daypart.DINNER
                                      else [40, 32, 18, 7, 3])[0]
                lines = []
                for li in range(n_lines):
                    m = rng.choice(entrees) if li == 0 or rng.random() < 0.35 else rng.choice(others)
                    qty = rng.choices([1, 2, 3], [75, 20, 5])[0]
                    mods = []
                    for mod in m.available_modifiers:
                        if mod == "Extra sauce":
                            if local_day >= A_CAUSE_DATE and rng.random() < 0.40:
                                mods.append(mod)
                        elif rng.random() < 0.15:
                            mods.append(mod)
                    lines.append((m, qty, mods))
                raw.append({
                    "store_id": sid,
                    "placed_at": local_dt.astimezone(UTC),
                    "local_date": local_day,
                    "local_hour": hour,
                    "weekday": local_day.weekday(),
                    "daypart": dp,
                    "lines": lines,
                })
    raw.sort(key=lambda r: (r["placed_at"], r["store_id"]))
    return raw


def add_pending_claims(claims: list[dict], orders: list, customers: dict) -> None:
    """Make some claims `pending` (review not finished), as real data would have.

    1. Review backlog: store_fault claims reported in the last REVIEW_BACKLOG_HOURS before the end of
       data are still pending. store_fault and pending both count toward the M&I rate, so no rate changes.
    2. Fraud cluster (distractor for STORE-A): one customer_ref files FRAUD_CLUSTER_CLAIMS "entire order"
       claims in FRAUD_CLUSTER_DAYS, all still pending. fraud_signals should flag this customer_ref,
       and the agent should see it is too small to explain STORE-A's rise.
    """
    prng = random.Random(PENDING_SEED)
    data_end = datetime.combine(END_DATE + timedelta(days=1), time(0), UTC)
    backlog_start = data_end - timedelta(hours=REVIEW_BACKLOG_HOURS)
    for c in claims:
        if c["review_label"] == ReviewLabel.STORE_FAULT and c["reported_at"] >= backlog_start:
            c["review_label"] = ReviewLabel.PENDING
            c["reviewed_at"] = None

    zone = ZoneInfo(next(tz for sid, _, _, tz, *_ in STORES if sid == FRAUD_CLUSTER_STORE))
    claimed = {c["order_id"] for c in claims}
    first, last = FRAUD_CLUSTER_DAYS
    pool = sorted(
        (o for o in orders
         if o.store_id == FRAUD_CLUSTER_STORE and o.status == OrderStatus.DELIVERED
         and o.order_id not in claimed and first <= o.placed_at.astimezone(zone).date() <= last),
        key=lambda o: o.order_id,
    )
    customer = prng.choice(customers[FRAUD_CLUSTER_STORE])
    for o in prng.sample(pool, FRAUD_CLUSTER_CLAIMS):
        o.customer_ref = customer  # the same customer placed all of these orders
        claims.append(dict(
            order_id=o.order_id, store_id=o.store_id, item_id=None, item_name="Entire order",
            error_category=ErrorCategory.MISSING_ITEM, modifier_detail=None,
            customer_comments=prng.choice(FRAUD_COMMENTS), error_charge=o.subtotal,
            reported_at=o.delivered_at + timedelta(minutes=prng.randint(10, 90)),
            review_label=ReviewLabel.PENDING, reviewed_at=None,
        ))


def main() -> None:
    print("Resetting schemas and running Alembic migrations...")
    reset_schema()
    stores, menus = build_stores_and_menus()
    raw_orders = generate_orders(menus)

    orders, order_items, cancellations, claims = [], [], [], []
    seq = defaultdict(int)

    def next_id(prefix: str, width: int) -> str:
        seq[prefix] += 1
        return f"{prefix}-{seq[prefix]:0{width}d}"

    cxl_labels = list(CancellationCategory)
    # Synthetic customer pool per store (about 15 days of orders worth of distinct customers)
    customers = {}
    for sid, *_, per_day in STORES:
        customers[sid] = [next_id("CUST", 6) for _ in range(max(20, per_day * 15))]
    a_oos_days = {date(2026, 10, 24), date(2026, 10, 25), date(2026, 10, 26)}

    for r in raw_orders:
        oid = next_id("ORD", 6)
        sid, placed = r["store_id"], r["placed_at"]
        item_count = sum(q for _, q, _ in r["lines"])
        subtotal = sum(m.price * q for m, q, _ in r["lines"])

        # ---- cancellations (distractors) ----
        cancel_cat = None
        if sid == "STORE-A" and r["local_date"] in a_oos_days and rng.random() < 0.15:
            cancel_cat = CancellationCategory.ITEM_OUT_OF_STOCK
        elif sid == "STORE-B" and r["weekday"] == 4 and r["daypart"] == Daypart.DINNER and rng.random() < 0.12:
            cancel_cat = CancellationCategory.TOO_BUSY
        elif rng.random() < BASE_CANCEL_RATE:
            cancel_cat = rng.choices(cxl_labels, [35, 30, 10, 10, 15])[0]

        status = OrderStatus.CANCELED if cancel_cat else OrderStatus.DELIVERED
        delivered = None if cancel_cat else placed + timedelta(minutes=rng.randint(25, 55))
        orders.append(Order(
            order_id=oid, store_id=sid, customer_ref=rng.choice(customers[sid]), placed_at=placed, delivered_at=delivered, status=status,
            daypart=r["daypart"], item_count=item_count, subtotal=subtotal,
        ))
        for m, q, mods in r["lines"]:
            order_items.append(OrderItem(order_id=oid, item_id=m.item_id, quantity=q, modifiers=mods))

        if cancel_cat:
            oos_item = (rng.choice(r["lines"])[0].item_id
                        if cancel_cat == CancellationCategory.ITEM_OUT_OF_STOCK else None)
            cancellations.append(Cancellation(
                evidence_id=next_id("EV-CXL", 6), order_id=oid, store_id=sid, item_id=oos_item,
                cancellation_category=cancel_cat,
                canceled_at=placed + timedelta(minutes=rng.randint(3, 20)),
            ))
            continue

        # ---- claims ----
        new_claims = []  # (category, menu_item or None, modifier_detail, comment, label)
        lines = r["lines"]

        # Scenario A: Extra sauce not mapped to kitchen ticket
        if sid == "STORE-A" and r["local_date"] >= A_CAUSE_DATE:
            seen = set()
            for m, q, mods in lines:
                if "Extra sauce" in mods and m.item_id not in seen and rng.random() < 0.18:
                    seen.add(m.item_id)
                    cat = rng.choice([ErrorCategory.INGREDIENT_ERROR, ErrorCategory.INCORRECT_ITEM])
                    new_claims.append((cat, m, "Extra sauce", fmt_comment(SAUCE_COMMENTS, m.name),
                                       pick_review_label(0.90, 0.02)))

        # Scenario B: large dinner orders lose a whole bag
        if (sid == "STORE-B" and r["local_date"] >= B_CAUSE_DATE and r["daypart"] == Daypart.DINNER
                and item_count >= 5 and rng.random() < 0.35):
            bag_items = list({m.item_id: m for m, _, _ in lines
                              if m.category in ("drink", "dessert", "side")}.values()) or [lines[-1][0]]
            label = pick_review_label(0.88, 0.02)
            for i, m in enumerate(bag_items[: rng.randint(1, 3)]):
                # the customer writes one comment for the whole claim; later lines carry none
                comment = fmt_comment(BAG_COMMENTS, m.name) if i == 0 else None
                new_claims.append((ErrorCategory.MISSING_ITEM, m, None, comment, label))

        # STORE-I has a slightly higher base rate (but too few orders to open a case)
        base_rate = 0.04 if sid == "STORE-I" else BASE_CLAIM_RATE
        if not new_claims and rng.random() < base_rate:
            cat = rng.choices(list(ErrorCategory), [45, 25, 20, 10])[0]
            m, _, mods = rng.choice(lines)
            if cat == ErrorCategory.WRONG_ORDER:
                new_claims.append((cat, None, None, fmt_comment(GENERIC_COMMENTS[cat], ""), pick_review_label()))
            else:
                mod_detail = rng.choice(mods) if (mods and cat == ErrorCategory.INGREDIENT_ERROR) else None
                new_claims.append((cat, m, mod_detail, fmt_comment(GENERIC_COMMENTS[cat], m.name),
                                   pick_review_label()))

        for cat, m, mod_detail, comment, label in new_claims:
            reported = delivered + timedelta(minutes=rng.randint(10, 180))
            if m is None:
                item_name, item_id, charge = "Entire order", None, subtotal
            else:
                item_name, item_id = m.name, m.item_id
                charge = m.price
            claims.append(dict(
                order_id=oid, store_id=sid, item_id=item_id, item_name=item_name, error_category=cat,
                modifier_detail=mod_detail, customer_comments=comment, error_charge=charge,
                reported_at=reported, review_label=label,
                reviewed_at=reported + timedelta(hours=rng.randint(20, 72)),
                _order=r,
            ))

    # ---- explicit distractors and spikes ----
    def add_claims_for(sid, n, pick_order, make):
        claimed = {c["order_id"] for c in claims}
        pool = [o for o in orders if o.store_id == sid and o.status == OrderStatus.DELIVERED
                and o.order_id not in claimed and pick_order(o)]
        for o in rng.sample(pool, n):
            claims.append(make(o))

    def fraud_claim(o):
        reported = o.delivered_at + timedelta(minutes=rng.randint(10, 90))
        return dict(order_id=o.order_id, store_id=o.store_id, item_id=None, item_name="Entire order",
                    error_category=ErrorCategory.MISSING_ITEM, modifier_detail=None,
                    customer_comments=rng.choice(FRAUD_COMMENTS), error_charge=o.subtotal,
                    reported_at=reported, review_label=ReviewLabel.FRAUD,
                    reviewed_at=reported + timedelta(hours=rng.randint(20, 72)))

    def in_window(start, end):
        return lambda o: datetime.combine(start, time(0), UTC) <= o.placed_at < datetime.combine(end, time(0), UTC)

    add_claims_for("STORE-A", 3, in_window(date(2026, 10, 28), date(2026, 11, 12)), fraud_claim)
    add_claims_for("STORE-B", 4, in_window(date(2026, 11, 1), date(2026, 11, 14)), fraud_claim)

    # STORE-J: 6 claims on Nov 8 only (lunch), 7-day rate should stay under threshold
    all_items = {m.item_id: m for items in menus.values() for m in items}
    order_lines = defaultdict(list)
    for oi in order_items:
        order_lines[oi.order_id].append(oi)

    def store_fault_missing_claim(o):
        oi = rng.choice(order_lines[o.order_id])
        m = all_items[oi.item_id]
        reported = o.delivered_at + timedelta(minutes=rng.randint(10, 90))
        return dict(order_id=o.order_id, store_id=o.store_id, item_id=m.item_id, item_name=m.name,
                    error_category=ErrorCategory.MISSING_ITEM, modifier_detail=None,
                    customer_comments=fmt_comment(GENERIC_COMMENTS[ErrorCategory.MISSING_ITEM], m.name),
                    error_charge=m.price, reported_at=reported, review_label=ReviewLabel.STORE_FAULT,
                    reviewed_at=reported + timedelta(hours=rng.randint(20, 72)))

    j_zone = ZoneInfo("America/New_York")
    add_claims_for(
        "STORE-J", 6,
        lambda o: o.placed_at.astimezone(j_zone).date() == J_SPIKE_DATE and o.daypart == Daypart.LUNCH,
        store_fault_missing_claim,
    )
    # STORE-I: 3 recent claims make its 7-day rate look high (~10%), but it has too few orders
    add_claims_for("STORE-I", 3, in_window(date(2026, 11, 9), date(2026, 11, 16)), store_fault_missing_claim)

    add_pending_claims(claims, orders, customers)

    # Assign claim evidence IDs in time order
    claims.sort(key=lambda c: (c["reported_at"], c["order_id"]))
    claim_rows = []
    for c in claims:
        c.pop("_order", None)
        claim_rows.append(MIClaim(evidence_id=next_id("EV-CLM", 6), **c))

    # ---- operational events (real causes + distractors) ----
    def local(sid_tz, d, hh, mm=0):
        return datetime.combine(d, time(hh, mm), ZoneInfo(sid_tz)).astimezone(UTC)

    chi = "America/Chicago"
    events_spec = [
        ("STORE-A", EventType.STORE_DOWNTIME, local(chi, date(2026, 10, 20), 17), local(chi, date(2026, 10, 20), 19),
         "Store paused on DoorDash for about 2 hours (tablet offline)."),
        ("STORE-A", EventType.MENU_CHANGE, local(chi, date(2026, 10, 30), 10), None,
         'Added paid modifier "Extra sauce" (+$0.99) to all entrees.'),
        ("STORE-A", EventType.MENU_CHANGE, local(chi, date(2026, 10, 30), 10, 5), None,
         'Renamed drink "Milk Tea" to "Bubble Milk Tea".'),
        ("STORE-B", EventType.MENU_CHANGE, local(chi, date(2026, 11, 1), 9), None,
         'Price change: "Pecan Pie Slice" from $4.49 to $4.99.'),
        ("STORE-B", EventType.PROMOTION, local(chi, date(2026, 11, 3), 0), local(chi, date(2026, 11, 10), 0),
         "Promotion: 20% off family meals (Nov 3-9)."),
        ("STORE-C", EventType.MENU_CHANGE, local(chi, date(2026, 10, 15), 9), None,
         'Added "Gluten-free crust" modifier to pizzas.'),
        ("STORE-D", EventType.STORE_DOWNTIME, local(chi, date(2026, 11, 2), 12), local(chi, date(2026, 11, 2), 13),
         "Store paused on DoorDash for about 1 hour (POS outage)."),
        ("STORE-F", EventType.POS_CHANGE, local("America/Los_Angeles", date(2026, 10, 22), 8), None,
         "POS integration updated to new menu sync version."),
        ("STORE-H", EventType.PROMOTION, local("America/Phoenix", date(2026, 10, 12), 0),
         local("America/Phoenix", date(2026, 10, 19), 0), "Promotion: free fries with any burger."),
    ]
    events_spec.sort(key=lambda e: e[2])
    events = [
        OperationalEvent(evidence_id=next_id("EV-EVT", 6), store_id=s, event_type=t, started_at=st,
                         ended_at=en, description=desc)
        for s, t, st, en, desc in events_spec
    ]

    golden = [
        GoldenScenario(
            scenario_id="GS-01", store_id="STORE-A", split="dev", cause_category="pos",
            true_cause="pos_modifier_not_mapped", cause_started_at=local(chi, A_CAUSE_DATE, 10),
            expected_outcome="diagnosed", expected_owner="merchant",
            expected_action="ask_merchant_fix_pos_modifier_mapping",
            key_evidence=["claims concentrated on modifier_detail 'Extra sauce' after Oct 30",
                          "Oct 30 menu_change adding the Extra sauce modifier"],
            distractors=["Oct 20 store downtime", "Oct 24-26 out-of-stock cancellations",
                         "same-day unrelated drink rename", "fraud-labeled claims",
                         "one customer_ref with 5 pending entire-order claims (Nov 6-15)"],
            notes="Extra sauce modifier added Oct 30 is not printed on the kitchen ticket.",
        ),
        GoldenScenario(
            scenario_id="GS-02", store_id="STORE-B", split="dev", cause_category="packing",
            true_cause="dinner_multi_bag_packing", cause_started_at=local(chi, B_CAUSE_DATE, 16),
            expected_outcome="diagnosed", expected_owner="merchant",
            expected_action="ask_merchant_add_dinner_bag_check",
            key_evidence=["missing_item claims concentrated in dinner orders with 5+ items after Nov 3",
                          "customer comments mention a whole bag missing",
                          "lunch and small orders stay normal"],
            distractors=["Nov 1 dessert price change", "Nov 3-9 promotion raising volume",
                         "Friday dinner too_busy cancellations all period", "fraud-labeled claims"],
            notes="Merchant confirmation needed; data shows the daypart pattern, not the crew.",
        ),
        GoldenScenario(
            scenario_id="GS-03", store_id="STORE-I", split="dev", cause_category="none",
            true_cause="none_low_volume", cause_started_at=None,
            expected_outcome="no_case", expected_owner="analyst", expected_action="no_case",
            key_evidence=["about 30 delivered orders per week, below minimum volume"],
            distractors=["high 7-day rate"],
            notes="Rate looks high but the sample is too small.",
        ),
        GoldenScenario(
            scenario_id="GS-04", store_id="STORE-J", split="dev", cause_category="none",
            true_cause="none_one_day_spike", cause_started_at=None,
            expected_outcome="no_case", expected_owner="analyst", expected_action="no_case",
            key_evidence=["7-day rate within normal range"],
            distractors=["6 claims on Nov 8 only"],
            notes="One-day spike that does not persist.",
        ),
    ]

    print("Inserting rows...")
    with SessionLocal() as session:
        session.add_all(stores)
        session.flush()
        session.add_all([m for items in menus.values() for m in items])
        session.flush()
        session.add_all(orders)
        session.flush()
        session.add_all(order_items)
        session.add_all(cancellations)
        session.add_all(claim_rows)
        session.add_all(events)
        session.add_all(golden)
        session.commit()

    print(
        f"Done: {len(stores)} stores, {sum(len(v) for v in menus.values())} menu items, "
        f"{len(orders)} orders, {len(order_items)} order items, {len(claim_rows)} claims, "
        f"{len(cancellations)} cancellations, {len(events)} events, {len(golden)} golden scenarios."
    )


if __name__ == "__main__":
    main()

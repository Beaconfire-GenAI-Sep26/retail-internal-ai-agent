"""Build the Domain fixtures used by the agent's tests and by AGENT_DOMAIN_MODE=fixtures.

This is test tooling, not the Domain Service. It simulates orders, claims, cancellations and events
for STORE-A (POS modifier), STORE-B (dinner packing) and STORE-C (a flat store), following the
scenarios and parameters C-01 describes, then answers a fixed list of diagnostic queries with the
rate rules in docs/contracts.md. The numbers and claim IDs are synthetic: close to the seeded
database, not equal to it. Event IDs follow the seed's numbering.

Run from agent/:  uv run python scripts/make_fixtures.py
"""

from __future__ import annotations

import json
import random
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

OUT = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "domain"

START, END = date(2026, 10, 5), date(2026, 11, 15)
TRIGGER = (date(2026, 11, 9), date(2026, 11, 15))
BASELINE = (date(2026, 10, 12), date(2026, 11, 8))
A_CAUSE, B_CAUSE = date(2026, 10, 30), date(2026, 11, 3)
B_PROMO = (date(2026, 11, 3), date(2026, 11, 9))
MIN_GROUP_ORDERS = 30
FRAUD_MIN_PENDING_CLAIMS = 4
DEFAULT_LABELS = ("store_fault", "pending")
LABELS = ("store_fault", "not_store_fault", "fraud", "pending")
CATEGORIES = ("missing_item", "incorrect_item", "ingredient_error", "wrong_order")
DAYPARTS = ("breakfast", "lunch", "dinner", "late_night")
BUCKETS = ("1-2", "3-4", "5+")

rng = random.Random(24)

STORES = {
    "STORE-A": dict(name="Golden Wok Kitchen", city="Chicago", tz="America/Chicago", cuisine="chinese",
                    open=11, close=22, per_day=60, case_id="CASE-0001"),
    "STORE-B": dict(name="Lone Star Family Grill", city="Houston", tz="America/Chicago", cuisine="american",
                    open=11, close=22, per_day=70, case_id="CASE-0002"),
    "STORE-C": dict(name="Bella Forno Pizzeria", city="Chicago", tz="America/Chicago", cuisine="italian",
                    open=11, close=23, per_day=80, case_id="CASE-0003"),
}

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
}

HOUR_WEIGHTS = {11: 8, 12: 12, 13: 10, 14: 5, 15: 4, 16: 5, 17: 9, 18: 13, 19: 12, 20: 8, 21: 5, 22: 3}

GENERIC_COMMENTS = {
    "missing_item": ["My {item} was not in the bag.", "{item} missing from the order.", "Never received the {item}.", None],
    "incorrect_item": ["Got the wrong item instead of {item}.", "Received something else, not {item}.", None],
    "ingredient_error": ["{item} was made wrong, ingredients were off.",
                         "Asked for changes on {item} but they were ignored.", None],
    "wrong_order": ["This was someone else's order entirely.", "Whole order was wrong, none of it was mine."],
}
SAUCE_COMMENTS = [
    "Paid for extra sauce on the {item}, got none.", "No extra sauce at all even though I paid for it.",
    "Ordered {item} with extra sauce, came completely dry.", "Extra sauce was charged but missing.",
    "The {item} had no sauce, the add-on was ignored.", None,
]
BAG_COMMENTS = [
    "The whole second bag never arrived. No drinks, no dessert.",
    "Only got one bag, the {item} and the rest were missing.",
    "Half the order was missing, looks like a bag was left behind.", "Drinks and dessert bag missing.",
    "Missing the {item} and everything else that should have been in the other bag.",
    "Big family order, a whole bag was not included.", None,
]
FRAUD_COMMENTS = ["Everything was missing, refund all of it.", "Nothing in the bag was right. Full refund please."]


@dataclass
class Item:
    item_id: str
    name: str
    category: str
    price: float
    modifiers: list[str]


@dataclass
class Order:
    order_id: str
    store_id: str
    placed_at: datetime
    local_date: date
    daypart: str
    lines: list[tuple[Item, int, list[str]]]
    customer_ref: str
    status: str = "delivered"
    delivered_at: datetime | None = None

    @property
    def weekday(self) -> int:
        return self.local_date.weekday()

    @property
    def item_count(self) -> int:
        return sum(q for _, q, _ in self.lines)

    @property
    def item_ids(self) -> set[str]:
        return {m.item_id for m, _, _ in self.lines}

    @property
    def modifiers(self) -> set[str]:
        return {mod for _, _, mods in self.lines for mod in mods}

    @property
    def subtotal(self) -> float:
        return round(sum(m.price * q for m, q, _ in self.lines), 2)


@dataclass
class Claim:
    order: Order
    item: Item | None
    error_category: str
    modifier_detail: str | None
    comment: str | None
    label: str
    reported_at: datetime
    evidence_id: str = ""

    @property
    def item_id(self) -> str | None:
        return self.item.item_id if self.item else None


@dataclass
class Cancellation:
    order: Order
    item_id: str | None
    category: str
    canceled_at: datetime
    evidence_id: str = ""


@dataclass
class Event:
    evidence_id: str
    store_id: str
    event_type: str
    started_at: datetime
    ended_at: datetime | None
    description: str


@dataclass
class Store:
    store_id: str
    meta: dict[str, Any]
    menu: list[Item]
    orders: list[Order] = field(default_factory=list)
    claims: list[Claim] = field(default_factory=list)
    cancellations: list[Cancellation] = field(default_factory=list)
    events: list[Event] = field(default_factory=list)

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.meta["tz"])

    @property
    def delivered(self) -> list[Order]:
        return [o for o in self.orders if o.status == "delivered"]


# --- Simulation ------------------------------------------------------------------------------


def iso(dt: datetime) -> str:
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def daypart_for(hour: int) -> str:
    if 5 <= hour <= 10:
        return "breakfast"
    if 11 <= hour <= 15:
        return "lunch"
    if 16 <= hour <= 20:
        return "dinner"
    return "late_night"


def pick_label(store_fault_p: float, fraud_p: float) -> str:
    r = rng.random()
    if r < fraud_p:
        return "fraud"
    if r < fraud_p + store_fault_p:
        return "store_fault"
    return "not_store_fault"


def fmt_comment(templates: list[str | None], item_name: str) -> str | None:
    t = rng.choice(templates)
    return t.format(item=item_name) if t else None


def build_store(store_id: str) -> Store:
    meta = STORES[store_id]
    letter = store_id.split("-")[1]
    items = []
    for i, (name, cat, price, mods) in enumerate(MENUS[meta["cuisine"]], start=1):
        mods = list(mods)
        if store_id == "STORE-A" and cat == "entree":
            mods.append("Extra sauce")
        items.append(Item(f"ITEM-{letter}-{i:03d}", name, cat, price, mods))
    return Store(store_id, meta, items)


def simulate(store: Store, customer_offset: int) -> None:
    meta, tz = store.meta, store.tz
    hours = [h for h in range(meta["open"], meta["close"])]
    weights = [HOUR_WEIGHTS.get(h, 1) for h in hours]
    entrees = [m for m in store.menu if m.category == "entree"]
    others = [m for m in store.menu if m.category != "entree"]
    customers = [f"CUST-{customer_offset + i:06d}" for i in range(1, meta["per_day"] * 15 + 1)]
    d = START
    while d <= END:
        n = meta["per_day"] * (1.2 if d.weekday() in (4, 5) else 1.0)
        if store.store_id == "STORE-B" and B_PROMO[0] <= d <= B_PROMO[1]:
            n *= 1.25
        n = max(0, round(rng.gauss(n, max(1.0, n * 0.12))))
        for _ in range(n):
            hour = rng.choices(hours, weights)[0]
            placed = datetime.combine(d, time(hour, rng.randint(0, 59)), tz)
            dp = daypart_for(hour)
            n_lines = rng.choices([1, 2, 3, 4, 5], [25, 30, 25, 12, 8] if dp == "dinner" else [40, 32, 18, 7, 3])[0]
            lines = []
            for li in range(n_lines):
                m = rng.choice(entrees) if li == 0 or rng.random() < 0.35 else rng.choice(others)
                qty = rng.choices([1, 2, 3], [75, 20, 5])[0]
                mods = []
                for mod in m.modifiers:
                    if mod == "Extra sauce":
                        if d >= A_CAUSE and rng.random() < 0.40:
                            mods.append(mod)
                    elif rng.random() < 0.15:
                        mods.append(mod)
                lines.append((m, qty, mods))
            order = Order("", store.store_id, placed.astimezone(UTC), d, dp, lines, rng.choice(customers))
            store.orders.append(order)
            cancel = None
            if store.store_id == "STORE-A" and date(2026, 10, 24) <= d <= date(2026, 10, 26) and rng.random() < 0.15:
                cancel = "item_out_of_stock"
            elif store.store_id == "STORE-B" and d.weekday() == 4 and dp == "dinner" and rng.random() < 0.12:
                cancel = "too_busy"
            elif rng.random() < 0.012:
                cancel = rng.choices(
                    ["item_out_of_stock", "too_busy", "menu_data_mismatch", "pos_technical_error", "other"],
                    [35, 30, 10, 10, 15],
                )[0]
            if cancel:
                order.status = "canceled"
                oos = rng.choice(lines)[0].item_id if cancel == "item_out_of_stock" else None
                store.cancellations.append(
                    Cancellation(order, oos, cancel, order.placed_at + timedelta(minutes=rng.randint(3, 20)))
                )
                continue
            order.delivered_at = order.placed_at + timedelta(minutes=rng.randint(25, 55))
            new: list[tuple[str, Item | None, str | None, str | None, str]] = []
            if store.store_id == "STORE-A" and d >= A_CAUSE:
                seen = set()
                for m, _, mods in lines:
                    if "Extra sauce" in mods and m.item_id not in seen and rng.random() < 0.18:
                        seen.add(m.item_id)
                        cat = rng.choice(["ingredient_error", "incorrect_item"])
                        new.append((cat, m, "Extra sauce", fmt_comment(SAUCE_COMMENTS, m.name), pick_label(0.90, 0.02)))
            if (store.store_id == "STORE-B" and d >= B_CAUSE and dp == "dinner" and order.item_count >= 5
                    and rng.random() < 0.35):
                bag = list({m.item_id: m for m, _, _ in lines if m.category in ("drink", "dessert", "side")}.values())
                bag = bag or [lines[-1][0]]
                label = pick_label(0.88, 0.02)
                for i, m in enumerate(bag[: rng.randint(1, 3)]):
                    new.append(("missing_item", m, None, fmt_comment(BAG_COMMENTS, m.name) if i == 0 else None, label))
            if not new and rng.random() < 0.014:
                cat = rng.choices(list(CATEGORIES), [45, 25, 20, 10])[0]
                m, _, mods = rng.choice(lines)
                if cat == "wrong_order":
                    new.append((cat, None, None, fmt_comment(GENERIC_COMMENTS[cat], ""), pick_label(0.75, 0.08)))
                else:
                    detail = rng.choice(mods) if mods and cat == "ingredient_error" else None
                    new.append((cat, m, detail, fmt_comment(GENERIC_COMMENTS[cat], m.name), pick_label(0.75, 0.08)))
            for cat, m, detail, comment, label in new:
                reported = order.delivered_at + timedelta(minutes=rng.randint(10, 180))
                store.claims.append(Claim(order, m, cat, detail, comment, label, reported))
        d += timedelta(days=1)

    fraud_n, fraud_window = {"STORE-A": (3, (date(2026, 10, 28), date(2026, 11, 11))),
                             "STORE-B": (4, (date(2026, 11, 1), date(2026, 11, 13)))}.get(store.store_id, (0, None))
    if fraud_n:
        claimed = {id(c.order) for c in store.claims}
        pool = [o for o in store.delivered if id(o) not in claimed and fraud_window[0] <= o.local_date <= fraud_window[1]]
        for o in rng.sample(pool, fraud_n):
            reported = o.delivered_at + timedelta(minutes=rng.randint(10, 90))
            store.claims.append(Claim(o, None, "missing_item", None, rng.choice(FRAUD_COMMENTS), "fraud", reported))


def add_events(stores: dict[str, Store]) -> None:
    chi = ZoneInfo("America/Chicago")

    def at(d: date, hh: int, mm: int = 0) -> datetime:
        return datetime.combine(d, time(hh, mm), chi).astimezone(UTC)

    specs = [
        ("EV-EVT-000002", "STORE-C", "menu_change", at(date(2026, 10, 15), 9), None,
         'Added "Gluten-free crust" modifier to pizzas.'),
        ("EV-EVT-000003", "STORE-A", "store_downtime", at(date(2026, 10, 20), 17), at(date(2026, 10, 20), 19),
         "Store paused on DoorDash for about 2 hours (tablet offline)."),
        ("EV-EVT-000005", "STORE-A", "menu_change", at(A_CAUSE, 10), None,
         'Added paid modifier "Extra sauce" (+$0.99) to all entrees.'),
        ("EV-EVT-000006", "STORE-A", "menu_change", at(A_CAUSE, 10, 5), None,
         'Renamed drink "Milk Tea" to "Bubble Milk Tea".'),
        ("EV-EVT-000007", "STORE-B", "menu_change", at(date(2026, 11, 1), 9), None,
         'Price change: "Pecan Pie Slice" from $4.49 to $4.99.'),
        ("EV-EVT-000009", "STORE-B", "promotion", at(B_CAUSE, 0), at(date(2026, 11, 10), 0),
         "Promotion: 20% off family meals (Nov 3-9)."),
    ]
    for eid, sid, etype, started, ended, desc in specs:
        stores[sid].events.append(Event(eid, sid, etype, started, ended, desc))


def assign_ids(stores: dict[str, Store]) -> None:
    orders = sorted((o for s in stores.values() for o in s.orders), key=lambda o: (o.placed_at, o.store_id))
    for i, o in enumerate(orders, start=1):
        o.order_id = f"ORD-{i:06d}"
    claims = sorted((c for s in stores.values() for c in s.claims), key=lambda c: (c.reported_at, c.order.order_id))
    for i, c in enumerate(claims, start=1):
        c.evidence_id = f"EV-CLM-{i:06d}"
    cxls = sorted((x for s in stores.values() for x in s.cancellations), key=lambda x: (x.canceled_at, x.order.order_id))
    for i, x in enumerate(cxls, start=1):
        x.evidence_id = f"EV-CXL-{i:06d}"


# --- Evidence records ------------------------------------------------------------------------


def claim_record(c: Claim) -> dict[str, Any]:
    name = c.item.name if c.item else "Entire order"
    return {
        "evidence_id": c.evidence_id,
        "type": "claim",
        "store_id": c.order.store_id,
        "occurred_at": iso(c.reported_at),
        "summary": f"{c.error_category} claim on {name}, {c.order.daypart} order with {c.order.item_count} items",
        "attributes": {
            "order_id": c.order.order_id,
            "item_id": c.item_id,
            "item_name": name,
            "error_category": c.error_category,
            "modifier_detail": c.modifier_detail,
            "customer_comments": c.comment,
            "error_charge": c.item.price if c.item else c.order.subtotal,
            "reported_at": iso(c.reported_at),
            "review_label": c.label,
            "reviewed_at": None if c.label == "pending" else iso(c.reported_at + timedelta(hours=30)),
            "daypart": c.order.daypart,
            "item_count": c.order.item_count,
            "customer_ref": c.order.customer_ref,
        },
    }


def cancellation_record(x: Cancellation) -> dict[str, Any]:
    return {
        "evidence_id": x.evidence_id,
        "type": "cancellation",
        "store_id": x.order.store_id,
        "occurred_at": iso(x.canceled_at),
        "summary": f"{x.category} cancellation, {x.order.daypart} order",
        "attributes": {
            "order_id": x.order.order_id,
            "item_id": x.item_id,
            "cancellation_category": x.category,
            "canceled_at": iso(x.canceled_at),
            "daypart": x.order.daypart,
        },
    }


def event_record(e: Event, tz: ZoneInfo) -> dict[str, Any]:
    return {
        "evidence_id": e.evidence_id,
        "type": "operational_event",
        "store_id": e.store_id,
        "occurred_at": iso(e.started_at),
        "summary": f"{e.event_type} on {e.started_at.astimezone(tz).date().isoformat()}: {e.description}",
        "attributes": {
            "event_type": e.event_type,
            "started_at": iso(e.started_at),
            "ended_at": iso(e.ended_at) if e.ended_at else None,
            "description": e.description,
        },
    }


# --- Query evaluation (the contract's rate rules) ---------------------------------------------


def _d(s: str) -> date:
    return date.fromisoformat(s)


def bucket(n: int) -> str:
    return "1-2" if n <= 2 else "3-4" if n <= 4 else "5+"


def order_in(o: Order, f: dict[str, Any], *, claim_side: bool = False) -> bool:
    if "start" in f and o.local_date < _d(f["start"]):
        return False
    if "end" in f and o.local_date > _d(f["end"]):
        return False
    if "daypart" in f and o.daypart not in f["daypart"]:
        return False
    if "weekday" in f and o.weekday not in f["weekday"]:
        return False
    if "item_count_min" in f and o.item_count < f["item_count_min"]:
        return False
    if "item_count_max" in f and o.item_count > f["item_count_max"]:
        return False
    if not claim_side:
        if "item_id" in f and not o.item_ids & set(f["item_id"]):
            return False
        if "modifiers" in f and not o.modifiers & set(f["modifiers"]):
            return False
    return True


def claim_in(c: Claim, f: dict[str, Any], labels: tuple[str, ...] | None = None) -> bool:
    labels = tuple(f.get("review_label", DEFAULT_LABELS)) if labels is None else labels
    if c.label not in labels or not order_in(c.order, f, claim_side=True):
        return False
    if "item_id" in f and c.item_id not in f["item_id"]:
        return False
    if "modifiers" in f and c.modifier_detail not in f["modifiers"]:
        return False
    if "error_category" in f and c.error_category not in f["error_category"]:
        return False
    return True


def excluded_notes(store: Store, f: dict[str, Any]) -> list[str]:
    labels = tuple(f.get("review_label", DEFAULT_LABELS))
    notes = []
    for label in ("fraud", "not_store_fault"):
        if label in labels:
            continue
        n = sum(1 for c in store.claims if claim_in(c, f, labels=(label,)))
        if n:
            notes.append(f"{n} claims excluded: review_label {label}")
    return notes


def rate(num: int, den: int) -> float | None:
    return round(num / den, 4) if den >= MIN_GROUP_ORDERS else None


def share(num: int, den: int) -> float | None:
    return round(num / den, 4) if den else None


def pct(v: float | None) -> str:
    return "n/a" if v is None else f"{v * 100:.1f}%"


def newest(claims: list[Claim]) -> list[Claim]:
    return sorted(claims, key=lambda c: (-c.reported_at.timestamp(), c.evidence_id))


def result(tool: str, store: Store, window: tuple[str, str], **kw: Any) -> dict[str, Any]:
    out = {
        "tool": tool, "store_id": store.store_id, "window": {"start": window[0], "end": window[1]},
        "eligible_orders": 0, "pending_claims": 0, "data_sufficient": False, "headline": "",
        "metrics": [], "evidence_ids": [], "evidence": [], "notes": [],
    }
    out.update(kw)
    return out


NATURAL_ORDER = {"daypart": DAYPARTS, "item_count": BUCKETS}


def claim_breakdown(store: Store, f: dict[str, Any], group_by: str) -> dict[str, Any]:
    orders = [o for o in store.delivered if order_in(o, f)]
    claims = [c for c in store.claims if claim_in(c, f)]
    total_o, total_c = len(orders), len(claims)
    g_orders: dict[str, int] = defaultdict(int)
    g_claims: dict[str, list[Claim]] = defaultdict(list)
    claim_level = group_by in ("error_category", "review_label")
    notes = excluded_notes(store, f)
    key_of = {
        "daypart": lambda o: o.daypart,
        "weekday": lambda o: str(o.weekday),
        "item_count": lambda o: bucket(o.item_count),
        "day": lambda o: o.local_date.isoformat(),
    }
    if group_by in key_of:
        for o in orders:
            g_orders[key_of[group_by](o)] += 1
        for c in claims:
            g_claims[key_of[group_by](c.order)].append(c)
    elif group_by == "item_id":
        for o in orders:
            for iid in o.item_ids:
                g_orders[iid] += 1
        for c in claims:
            g_claims[c.item_id or "unknown"].append(c)
        if "unknown" in g_claims:
            g_orders["unknown"] = total_o
    elif group_by == "modifier":
        for o in orders:
            for m in o.modifiers:
                g_orders[m] += 1
        nulls = 0
        for c in claims:
            if c.modifier_detail:
                g_claims[c.modifier_detail].append(c)
            else:
                nulls += 1
        notes.append(f"{nulls} of {total_c} claims have no modifier_detail")
    else:
        attr = "error_category" if group_by == "error_category" else "label"
        for c in claims:
            g_claims[getattr(c, attr)].append(c)
    labels = sorted(set(g_orders) | set(g_claims))

    def lift(g: str) -> float:
        cs = share(len(g_claims[g]), total_c) or 0.0
        if claim_level:
            return cs
        os_ = share(g_orders[g], total_o) or 0.0
        return cs / os_ if os_ else 0.0

    def enough(g: str) -> bool:
        return (total_o if claim_level else g_orders[g]) >= MIN_GROUP_ORDERS

    ranked = sorted(labels, key=lambda g: (not enough(g), -lift(g), g))
    if group_by in NATURAL_ORDER:
        display = sorted(labels, key=lambda g: NATURAL_ORDER[group_by].index(g))
    elif group_by in ("day", "weekday"):
        display = sorted(labels, key=lambda g: (int(g) if group_by == "weekday" else g))
    else:
        display = ranked
    metrics = []
    for g in display:
        den = total_o if claim_level else g_orders[g]
        n = len(g_claims[g])
        label = f"{group_by}={g}"
        metrics.append({"name": "claim_rate", "group": label, "value": rate(n, den), "numerator": n,
                        "denominator": den, "unit": "rate"})
        metrics.append({"name": "claim_share", "group": label, "value": share(n, total_c), "numerator": n,
                        "denominator": total_c, "unit": "share"})
        if claim_level:
            metrics.append({"name": "order_share", "group": label, "value": None, "numerator": None,
                            "denominator": None, "unit": "share"})
        else:
            metrics.append({"name": "order_share", "group": label, "value": share(g_orders[g], total_o),
                            "numerator": g_orders[g], "denominator": total_o, "unit": "share"})
    evidence_ids = [c.evidence_id for g in ranked for c in newest(g_claims[g])]
    top = next((g for g in ranked if enough(g) and g_claims[g]), None)
    if top is None:
        headline = f"No group with enough orders has claims among {total_c} claims on {total_o} orders."
    elif claim_level:
        headline = f"{group_by}={top} has {pct(share(len(g_claims[top]), total_c))} of the {total_c} claims."
    else:
        headline = (f"{group_by}={top} has {pct(share(len(g_claims[top]), total_c))} of claims on "
                    f"{pct(share(g_orders[top], total_o))} of orders (lift {lift(top):.1f}), the highest of "
                    f"{sum(1 for g in labels if enough(g))} groups with enough orders.")
    return result("claim_breakdown", store, (f["start"], f["end"]), eligible_orders=total_o,
                  pending_claims=sum(c.label == "pending" for c in claims),
                  data_sufficient=total_o >= MIN_GROUP_ORDERS, headline=headline, metrics=metrics,
                  evidence_ids=evidence_ids, notes=notes)


def compare_periods(store: Store, req: dict[str, Any]) -> dict[str, Any]:
    split = _d(req["split_date"])
    b0, b1 = split - timedelta(days=req["days_before"]), split - timedelta(days=1)
    a0, a1 = split, split + timedelta(days=req["days_after"] - 1)
    target, control = req["target"], req["control"]

    def period(scope: dict[str, Any] | None, lo: date, hi: date, rest: bool) -> tuple[list[Order], list[Claim]]:
        span = {"start": lo.isoformat(), "end": hi.isoformat()}
        if rest:
            orders = [o for o in store.delivered if order_in(o, span) and not order_in(o, target)]
            ids = {id(o) for o in orders}
            claims = [c for c in store.claims if id(c.order) in ids and c.label in DEFAULT_LABELS]
        else:
            f = {**(scope or {}), **span}
            orders = [o for o in store.delivered if order_in(o, f)]
            claims = [c for c in store.claims if claim_in(c, f)]
        return orders, claims

    rest = control is None
    tb, ta = period(target, b0, b1, False), period(target, a0, a1, False)
    cb, ca = period(control, b0, b1, rest), period(control, a0, a1, rest)
    metrics = []
    for group, (before, after) in (("target", (tb, ta)), ("control", (cb, ca))):
        for name, (orders, claims) in (("rate_before", before), ("rate_after", after)):
            metrics.append({"name": name, "group": group, "value": rate(len(claims), len(orders)),
                            "numerator": len(claims), "denominator": len(orders), "unit": "rate"})
    notes = excluded_notes(store, {**target, "start": b0.isoformat(), "end": a1.isoformat()})
    if not tb[0]:
        notes.append(f"No eligible target orders from {b0} to {b1}, so the target's rate_before is null.")
    if rest:
        notes.append("Control: every order of the store outside the target.")
    m = {(x["name"], x["group"]): x["value"] for x in metrics}
    headline = (f"Target {pct(m[('rate_before', 'target')])} before and {pct(m[('rate_after', 'target')])} "
                f"from {split}; control {pct(m[('rate_before', 'control')])} before and "
                f"{pct(m[('rate_after', 'control')])}.")
    evidence = newest(ta[1]) + newest(tb[1]) + newest(cb[1] + ca[1])
    return result("compare_periods", store, (b0.isoformat(), a1.isoformat()),
                  eligible_orders=len(tb[0]) + len(ta[0]) + len(cb[0]) + len(ca[0]),
                  pending_claims=sum(c.label == "pending" for c in evidence),
                  data_sufficient=len(ta[0]) >= MIN_GROUP_ORDERS and len(cb[0]) >= MIN_GROUP_ORDERS
                  and len(ca[0]) >= MIN_GROUP_ORDERS,
                  headline=headline, metrics=metrics, evidence_ids=[c.evidence_id for c in evidence], notes=notes)


def cancellation_breakdown(store: Store, f: dict[str, Any], group_by: str) -> dict[str, Any]:
    placed = [o for o in store.orders if order_in(o, f)]
    ids = {id(o) for o in placed}
    cxls = [x for x in store.cancellations if id(x.order) in ids
            and ("cancellation_category" not in f or x.category in f["cancellation_category"])]
    g_orders: dict[str, int] = defaultdict(int)
    g_cxls: dict[str, list[Cancellation]] = defaultdict(list)
    key_of = {"daypart": lambda o: o.daypart, "weekday": lambda o: str(o.weekday),
              "day": lambda o: o.local_date.isoformat()}
    if group_by in key_of:
        for o in placed:
            g_orders[key_of[group_by](o)] += 1
        for x in cxls:
            g_cxls[key_of[group_by](x.order)].append(x)
    elif group_by == "item_id":
        for o in placed:
            for iid in o.item_ids:
                g_orders[iid] += 1
        for x in cxls:
            g_cxls[x.item_id or "unknown"].append(x)
        if "unknown" in g_cxls:
            g_orders["unknown"] = len(placed)
    else:
        for x in cxls:
            g_cxls[x.category].append(x)
        for g in g_cxls:
            g_orders[g] = len(placed)
    labels = sorted(set(g_cxls) | ({g for g in g_orders} if group_by in key_of else set()))

    def r(g: str) -> float:
        return len(g_cxls[g]) / g_orders[g] if g_orders[g] else 0.0

    ranked = sorted(labels, key=lambda g: (g_orders[g] < MIN_GROUP_ORDERS, -r(g), g))
    display = sorted(labels, key=lambda g: (int(g) if group_by == "weekday" else g)) if group_by in key_of else ranked
    metrics = []
    for g in display:
        label = f"{group_by}={g}"
        metrics.append({"name": "cancellation_rate", "group": label, "value": rate(len(g_cxls[g]), g_orders[g]),
                        "numerator": len(g_cxls[g]), "denominator": g_orders[g], "unit": "rate"})
        metrics.append({"name": "cancellation_count", "group": label, "value": len(g_cxls[g]),
                        "numerator": None, "denominator": None, "unit": "count"})
    evidence_ids = [x.evidence_id for g in ranked
                    for x in sorted(g_cxls[g], key=lambda x: (-x.canceled_at.timestamp(), x.evidence_id))]
    top = next((g for g in ranked if g_orders[g] >= MIN_GROUP_ORDERS and g_cxls[g]), None)
    headline = (f"{group_by}={top} has the highest cancellation rate, {pct(r(top))} "
                f"({len(g_cxls[top])} of {g_orders[top]} placed orders)." if top
                else f"{len(cxls)} cancellations on {len(placed)} placed orders.")
    return result("cancellation_breakdown", store, (f["start"], f["end"]), eligible_orders=len(placed),
                  data_sufficient=len(placed) >= MIN_GROUP_ORDERS, headline=headline, metrics=metrics,
                  evidence_ids=evidence_ids)


def sample_claims(store: Store, f: dict[str, Any], limit: int = 10) -> dict[str, Any]:
    claims = newest([c for c in store.claims if claim_in(c, f)])
    picked = claims[:limit]
    return result("sample_evidence", store, (f["start"], f["end"]), data_sufficient=True,
                  pending_claims=sum(c.label == "pending" for c in picked),
                  headline=f"{len(picked)} of {len(claims)} matching claims, newest first.",
                  evidence_ids=[c.evidence_id for c in picked], evidence=[claim_record(c) for c in picked])


def sample_cancellations(store: Store, f: dict[str, Any], limit: int = 10) -> dict[str, Any]:
    placed = {id(o) for o in store.orders if order_in(o, f)}
    cxls = sorted([x for x in store.cancellations if id(x.order) in placed
                   and ("cancellation_category" not in f or x.category in f["cancellation_category"])],
                  key=lambda x: (-x.canceled_at.timestamp(), x.evidence_id))
    picked = cxls[:limit]
    return result("sample_evidence", store, (f["start"], f["end"]), data_sufficient=True,
                  headline=f"{len(picked)} of {len(cxls)} matching cancellations, newest first.",
                  evidence_ids=[x.evidence_id for x in picked], evidence=[cancellation_record(x) for x in picked])


def event_log(store: Store, start: str, end: str) -> dict[str, Any]:
    evs = sorted((e for e in store.events if _d(start) <= e.started_at.astimezone(store.tz).date() <= _d(end)),
                 key=lambda e: (e.started_at, e.evidence_id))
    return result("event_log", store, (start, end), data_sufficient=True,
                  headline=f"{len(evs)} events from {start} to {end} (all types).",
                  evidence_ids=[e.evidence_id for e in evs], evidence=[event_record(e, store.tz) for e in evs])


def overview(store: Store, start: str, end: str) -> dict[str, Any]:
    span = {"start": start, "end": end}
    orders = [o for o in store.delivered if order_in(o, span)]
    ids = {id(o) for o in orders}
    in_window = [c for c in store.claims if id(c.order) in ids]
    attributable = [c for c in in_window if c.label in DEFAULT_LABELS]
    metrics = [{"name": "claim_rate", "group": None, "value": rate(len(attributable), len(orders)),
                "numerator": len(attributable), "denominator": len(orders), "unit": "rate"}]
    for label in LABELS:
        n = sum(c.label == label for c in in_window)
        metrics.append({"name": "claim_count", "group": f"review_label={label}", "value": n, "numerator": None,
                        "denominator": None, "unit": "count"})
    for cat in CATEGORIES:
        n = sum(c.error_category == cat for c in attributable)
        metrics.append({"name": "claim_count", "group": f"error_category={cat}", "value": n, "numerator": None,
                        "denominator": None, "unit": "count"})
    per_day_o: dict[date, int] = defaultdict(int)
    per_day_c: dict[date, int] = defaultdict(int)
    for o in orders:
        per_day_o[o.local_date] += 1
    for c in attributable:
        per_day_c[c.order.local_date] += 1
    d = _d(start)
    while d <= _d(end):
        metrics.append({"name": "daily_claim_rate", "group": f"day={d.isoformat()}",
                        "value": rate(per_day_c[d], per_day_o[d]), "numerator": per_day_c[d],
                        "denominator": per_day_o[d], "unit": "rate"})
        d += timedelta(days=1)
    last7 = [o for o in orders if o.local_date > _d(end) - timedelta(days=7)]
    last7_ids = {id(o) for o in last7}
    last7_c = sum(1 for c in attributable if id(c.order) in last7_ids)
    headline = (f"Claim rate {pct(share(len(attributable), len(orders)))} ({len(attributable)} claims on "
                f"{len(orders)} eligible orders) from {start} to {end}; the last 7 days ran at "
                f"{pct(share(last7_c, len(last7)))}.")
    return result("store_overview", store, (start, end), eligible_orders=len(orders),
                  pending_claims=sum(c.label == "pending" for c in attributable),
                  data_sufficient=len(orders) >= MIN_GROUP_ORDERS, headline=headline, metrics=metrics,
                  evidence_ids=[c.evidence_id for c in newest(attributable)], notes=excluded_notes(store, span))


def fraud_signals(store: Store, start: str, end: str) -> dict[str, Any]:
    span = {"start": start, "end": end}
    orders = [o for o in store.delivered if order_in(o, span)]
    pending = [c for c in store.claims if claim_in(c, span, labels=("pending",))]
    by_ref: dict[str, list[Claim]] = defaultdict(list)
    for c in pending:
        by_ref[c.order.customer_ref].append(c)
    flagged = sorted((r for r, cs in by_ref.items() if len(cs) >= FRAUD_MIN_PENDING_CLAIMS),
                     key=lambda r: (-len(by_ref[r]), r))
    metrics = [{"name": "claim_count", "group": f"customer_ref={r}", "value": len(by_ref[r]), "numerator": None,
                "denominator": None, "unit": "count"} for r in flagged]
    headline = (f"{len(flagged)} customer_ref values have {FRAUD_MIN_PENDING_CLAIMS} or more pending claims."
                if flagged else f"No customer_ref has {FRAUD_MIN_PENDING_CLAIMS} or more pending claims in the window.")
    return result("fraud_signals", store, (start, end), eligible_orders=len(orders),
                  pending_claims=len(pending), data_sufficient=len(orders) >= MIN_GROUP_ORDERS,
                  headline=headline, metrics=metrics,
                  evidence_ids=[c.evidence_id for r in flagged for c in newest(by_ref[r])])


# --- Case, menu, catalog -----------------------------------------------------------------------


def case_detail(store: Store) -> dict[str, Any]:
    def stats(lo: date, hi: date) -> tuple[int, int]:
        span = {"start": lo.isoformat(), "end": hi.isoformat()}
        orders = [o for o in store.delivered if order_in(o, span)]
        ids = {id(o) for o in orders}
        return len(orders), sum(1 for c in store.claims if id(c.order) in ids and c.label in DEFAULT_LABELS)

    t_o, t_c = stats(*TRIGGER)
    b_o, b_c = stats(*BASELINE)
    mi_rate, baseline = round(t_c / t_o, 4), round(b_c / b_o, 4)
    daily = []
    d = START
    while d <= END:
        o, c = stats(d, d)
        daily.append({"date": d.isoformat(), "rate": rate(c, o), "claims": c, "eligible_orders": o})
        d += timedelta(days=1)
    tz = store.tz
    meta = store.meta
    return {
        "case_id": meta["case_id"], "store_id": store.store_id, "store_name": meta["name"], "status": "open",
        "trigger_rule": "over_goal" if mi_rate > 0.05 else "spike_vs_baseline",
        "window_start": iso(datetime.combine(TRIGGER[0], time(0), tz)),
        "window_end": iso(datetime.combine(TRIGGER[1], time(23, 59, 59), tz)),
        "mi_rate": mi_rate, "baseline_rate": baseline, "eligible_orders": t_o, "attributable_claims": t_c,
        "goal_rate": 0.05, "opened_at": "2026-11-16T14:00:00Z", "updated_at": "2026-11-16T14:00:00Z",
        "active_investigation_id": None, "reopen_count": 0, "last_error": None,
        "store": {"store_id": store.store_id, "name": meta["name"], "city": meta["city"], "timezone": meta["tz"],
                  "cuisine": meta["cuisine"]},
        "daily_rates": daily, "investigation_ids": [], "proposals": [], "rechecks": [],
    }


def menu(store: Store) -> list[dict[str, Any]]:
    return [{"item_id": m.item_id, "store_id": store.store_id, "name": m.name, "category": m.category,
             "price": m.price, "available_modifiers": m.modifiers} for m in store.menu]


# --- The queries each store's fixtures answer ---------------------------------------------------

FULL = ("2026-10-05", "2026-11-15")
A_POST = ("2026-10-30", "2026-11-15")
B_POST = ("2026-11-03", "2026-11-15")
SAUCE = {"modifiers": ["Extra sauce"]}
A_CATS = {"error_category": ["incorrect_item", "ingredient_error"]}
B_LARGE_DINNER = {"daypart": ["dinner"], "item_count_min": 5}

BREAKDOWNS = {
    "STORE-A": [
        ("modifier", {}, [FULL, A_POST]), ("item_id", {}, [FULL, A_POST]), ("error_category", {}, [FULL, A_POST]),
        ("daypart", {}, [FULL]), ("item_count", {}, [FULL]), ("day", {}, [FULL]), ("weekday", {}, [FULL]),
        ("day", SAUCE, [FULL]), ("item_id", SAUCE, [A_POST]), ("modifier", A_CATS, [FULL, A_POST]),
        ("day", A_CATS, [FULL]), ("error_category", SAUCE, [A_POST]),
    ],
    "STORE-B": [
        ("item_count", {}, [FULL, B_POST]), ("daypart", {}, [FULL, B_POST]), ("error_category", {}, [FULL, B_POST]),
        ("item_id", {}, [FULL, B_POST]), ("modifier", {}, [FULL]), ("day", {}, [FULL]), ("weekday", {}, [FULL]),
        ("daypart", {"item_count_min": 5}, [FULL, B_POST]), ("item_count", {"daypart": ["dinner"]}, [FULL, B_POST]),
        ("day", B_LARGE_DINNER, [FULL]), ("weekday", B_LARGE_DINNER, [B_POST]), ("item_id", B_LARGE_DINNER, [B_POST]),
        ("error_category", B_LARGE_DINNER, [B_POST]),
    ],
    "STORE-C": [
        ("item_id", {}, [FULL]), ("modifier", {}, [FULL]), ("daypart", {}, [FULL]), ("item_count", {}, [FULL]),
        ("error_category", {}, [FULL]), ("day", {}, [FULL]), ("weekday", {}, [FULL]),
    ],
}
COMPARES = {
    "STORE-A": [
        (SAUCE, None, "2026-10-30", 14, 17), (SAUCE, None, "2026-11-06", 7, 10),
        ({"item_id": ["ITEM-A-011"]}, None, "2026-10-30", 14, 17), ({}, None, "2026-10-30", 14, 17),
    ],
    "STORE-B": [
        (B_LARGE_DINNER, None, "2026-11-10", 7, 6), (B_LARGE_DINNER, None, "2026-11-03", 14, 13),
        ({"item_id": ["ITEM-B-013"]}, None, "2026-11-01", 14, 15), ({"daypart": ["dinner"]}, None, "2026-11-03", 14, 13),
        ({"item_count_min": 5}, None, "2026-11-03", 14, 13),
        (B_LARGE_DINNER, {"daypart": ["lunch"], "item_count_min": 5}, "2026-11-03", 14, 13),
    ],
    "STORE-C": [({"modifiers": ["Gluten-free crust"]}, None, "2026-10-15", 10, 28)],
}
CANCEL_BREAKDOWNS = {
    "STORE-A": [("cancellation_category", {}, [FULL]), ("day", {}, [FULL]),
                ("day", {"cancellation_category": ["item_out_of_stock"]}, [FULL]),
                ("item_id", {"cancellation_category": ["item_out_of_stock"]}, [FULL])],
    "STORE-B": [("cancellation_category", {}, [FULL]), ("weekday", {}, [FULL]),
                ("weekday", {"daypart": ["dinner"]}, [FULL]), ("cancellation_category", {"daypart": ["dinner"]}, [FULL]),
                ("day", {"daypart": ["dinner"]}, [FULL])],
    "STORE-C": [("cancellation_category", {}, [FULL])],
}
CLAIM_SAMPLES = {
    "STORE-A": [(SAUCE, A_POST), ({}, FULL), (A_CATS, A_POST)],
    "STORE-B": [(B_LARGE_DINNER, B_POST), ({}, FULL), ({"daypart": ["lunch"]}, B_POST)],
    "STORE-C": [({}, FULL)],
}
CANCEL_SAMPLES = {
    "STORE-A": [({"cancellation_category": ["item_out_of_stock"]}, FULL)],
    "STORE-B": [({"cancellation_category": ["too_busy"]}, FULL)],
    "STORE-C": [],
}


def checks_for(store: Store) -> list[dict[str, Any]]:
    sid = store.store_id
    out = []
    for group_by, flt, windows in BREAKDOWNS[sid]:
        for start, end in windows:
            out.append({"match": {"tool": "claim_breakdown", "group_by": group_by, "filter": flt},
                        "result": claim_breakdown(store, {"start": start, "end": end, **flt}, group_by)})
    for target, control, split, before, after in COMPARES[sid]:
        req = {"split_date": split, "days_before": before, "days_after": after, "target": target, "control": control}
        out.append({"match": {"tool": "compare_periods", "target": target, "control": control, "split_date": [split]},
                    "result": compare_periods(store, req)})
    for group_by, flt, windows in CANCEL_BREAKDOWNS[sid]:
        for start, end in windows:
            out.append({"match": {"tool": "cancellation_breakdown", "group_by": group_by, "filter": flt},
                        "result": cancellation_breakdown(store, {"start": start, "end": end, **flt}, group_by)})
    for flt, (start, end) in CLAIM_SAMPLES[sid]:
        out.append({"match": {"tool": "sample_evidence", "evidence_type": "claim", "filter": flt},
                    "result": sample_claims(store, {"start": start, "end": end, **flt})})
    for flt, (start, end) in CANCEL_SAMPLES[sid]:
        out.append({"match": {"tool": "sample_evidence", "evidence_type": "cancellation", "filter": flt},
                    "result": sample_cancellations(store, {"start": start, "end": end, **flt})})
    out.append({"match": {"tool": "event_log"}, "result": event_log(store, *FULL)})
    return out


def flagged_fraud_signals(store: Store) -> dict[str, Any]:
    """A fraud_signals result with one flagged customer_ref, for the suspect_cluster test."""
    base = fraud_signals(store, *FULL)
    picked = newest([c for c in store.claims if c.label in DEFAULT_LABELS])[:5]
    ref = "CUST-009999"
    base.update(
        pending_claims=5,
        headline=f"1 customer_ref values have {FRAUD_MIN_PENDING_CLAIMS} or more pending claims.",
        metrics=[{"name": "claim_count", "group": f"customer_ref={ref}", "value": 5, "numerator": None,
                  "denominator": None, "unit": "count"}],
        evidence_ids=[c.evidence_id for c in picked],
        notes=["Test fixture: one flagged customer_ref."],
    )
    return base


def write(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")


def main() -> None:
    stores = {sid: build_store(sid) for sid in STORES}
    for offset, sid in zip((0, 900, 1950), STORES):
        simulate(stores[sid], offset)
    add_events(stores)
    assign_ids(stores)
    # The action catalog isn't a fixture: the agent bundles it in app/data/catalog.json.
    for sid, store in stores.items():
        folder = OUT / sid
        write(folder / "case.json", case_detail(store))
        write(folder / "menu.json", menu(store))
        write(folder / "overview.json", overview(store, *FULL))
        write(folder / "fraud_signals.json", fraud_signals(store, *FULL))
        write(folder / "checks.json", checks_for(store))
        if sid == "STORE-B":
            write(folder / "fraud_signals_flagged.json", flagged_fraud_signals(store))
        att = sum(c.label in DEFAULT_LABELS for c in store.claims)
        print(f"{sid}: {len(store.orders)} orders, {len(store.claims)} claims ({att} attributable), "
              f"{len(store.cancellations)} cancellations, {len(store.events)} events")


if __name__ == "__main__":
    main()

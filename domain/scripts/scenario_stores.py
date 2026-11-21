"""Golden Dataset stores added in C-04 (STORE-K, STORE-L, STORE-M).

Each store is a labeled scenario: the answer (cause, owner, action) is written first, then the
data is generated to match it, with one or two distractors. The answer goes to `eval.golden_scenarios`,
which the agent can't read.

How these stores stay out of the way of the C-01 data
- They are generated after the C-01 stores, with their own random generator, so every C-01 row and ID
  (STORE-A..J orders, claims, events) is exactly the same as before C-04.
- Their IDs continue the C-01 sequences (ORD-, EV-CLM-, EV-CXL-, EV-EVT-, CUST-), in time order within
  this batch. A fixed seed gives the same IDs on every reset, so `key_evidence_ids` stay valid.

The holdout stores (`holdout_stores.py`) use the same builder, only with `--holdout`.
"""
import random
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import Callable
from zoneinfo import ZoneInfo

from domain.app.models import (
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

DEV_SEED = 24 + 2  # SEED + 2; SEED + 1 is the C-02 pending-claim generator


# ---------------------------------------------------------------------------
# Building blocks shared by the scenario stores
# ---------------------------------------------------------------------------
@dataclass
class Claim:
    category: ErrorCategory
    item: MenuItem | None  # None = the entire order
    modifier: str | None
    comment: str | None
    label: ReviewLabel
    signal: bool = False  # True when the claim is evidence for the labeled cause


@dataclass
class Spec:
    """One scenario store. The rule functions receive (order, rng, kit) and decide what happens to it."""
    store: tuple  # id, name, city, timezone, cuisine, open, close, orders per day
    golden: dict  # GoldenScenario fields except store_id, cause_started_at and key_evidence_ids
    cause_started: tuple  # (date, local hour)
    events: list  # (event type, start (date, hour), end (date, hour) or None, description, is_cause)
    added_modifiers: dict = field(default_factory=dict)  # item name -> modifiers added to the menu
    modifier_rate: Callable = None  # (modifier, local_date, rng) -> probability a line takes it
    claim_rule: Callable = None  # (order, rng, kit) -> list[Claim]
    cancel_rule: Callable = None  # (order, rng, kit) -> (category, item_id, signal) or None
    delivery_minutes: Callable = None  # (order, rng) -> minutes from placed to delivered
    after: Callable = None  # (raw orders, customers, claimed order IDs, rng, kit) -> [(claim row, signal)]


@dataclass
class Kit:
    """What a rule may use from the C-01 generator: menus, comment templates and the base rates."""
    menus: dict
    hour_weights: dict
    generic_comments: dict
    base_claim_rate: float
    base_cancel_rate: float
    start: date
    end: date

    def label(self, rng, store_fault=0.75, fraud=0.08) -> ReviewLabel:
        r = rng.random()
        if r < fraud:
            return ReviewLabel.FRAUD
        if r < fraud + store_fault:
            return ReviewLabel.STORE_FAULT
        return ReviewLabel.NOT_STORE_FAULT

    def comment(self, rng, templates, item_name="") -> str | None:
        t = rng.choice(templates)
        return t.format(item=item_name) if t else None

    def generic_claim(self, o, rng) -> list[Claim]:
        """The C-01 background claim: about 1.4% of delivered orders, any category."""
        if rng.random() >= self.base_claim_rate:
            return []
        cat = rng.choices(list(ErrorCategory), [45, 25, 20, 10])[0]
        m, _, mods = rng.choice(o["lines"])
        if cat == ErrorCategory.WRONG_ORDER:
            return [Claim(cat, None, None, self.comment(rng, self.generic_comments[cat]), self.label(rng))]
        mod = rng.choice(mods) if (mods and cat == ErrorCategory.INGREDIENT_ERROR) else None
        return [Claim(cat, m, mod, self.comment(rng, self.generic_comments[cat], m.name), self.label(rng))]


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
    return list(range(o, 24)) + list(range(0, c)) if c <= o else list(range(o, c))


def local_dt(tz: str, d: date, hour: int, minute: int = 0) -> datetime:
    return datetime.combine(d, time(hour, minute), ZoneInfo(tz))


def has_item(o, name: str) -> bool:
    return any(m.name == name for m, _, _ in o["lines"])


def line_item(o, name: str) -> MenuItem:
    return next(m for m, _, _ in o["lines"] if m.name == name)


# ---------------------------------------------------------------------------
# Builder
# ---------------------------------------------------------------------------
@dataclass
class Built:
    stores: list = field(default_factory=list)
    menu_items: list = field(default_factory=list)
    orders: list = field(default_factory=list)
    order_items: list = field(default_factory=list)
    cancellations: list = field(default_factory=list)
    claims: list = field(default_factory=list)
    events: list = field(default_factory=list)
    golden: list = field(default_factory=list)


def build(specs: list[Spec], seed: int, kit: Kit, next_id: Callable[[str, int], str]) -> Built:
    """Generate every row for `specs`. `next_id` continues the C-01 ID sequences."""
    rng = random.Random(seed)
    out = Built()
    menus, customers, raw = {}, {}, []

    for spec in specs:
        sid, name, city, tz, cuisine, o_s, c_s, per_day = spec.store
        out.stores.append(Store(
            store_id=sid, name=name, city=city, timezone=tz, cuisine=cuisine,
            opening_hours={"open": o_s, "close": c_s}, is_active=True,
            onboarded_at=datetime(2024, rng.randint(1, 12), rng.randint(1, 28), tzinfo=ZoneInfo("UTC")),
        ))
        letter = sid.split("-")[1]
        items = []
        for i, (iname, cat, price, mods) in enumerate(kit.menus[cuisine], start=1):
            items.append(MenuItem(
                item_id=f"ITEM-{letter}-{i:03d}", store_id=sid, name=iname, category=cat,
                price=Decimal(f"{price:.2f}"), available_modifiers=list(mods) + spec.added_modifiers.get(iname, []),
            ))
        menus[sid] = items
        out.menu_items += items
        customers[sid] = [next_id("CUST", 6) for _ in range(max(20, per_day * 15))]

        # Orders, same shape as C-01 (lunch and dinner peaks, larger dinner orders)
        zone = ZoneInfo(tz)
        hours = open_hours(o_s, c_s)
        weights = [kit.hour_weights.get(h, 1) for h in hours]
        entrees = [m for m in items if m.category == "entree"]
        others = [m for m in items if m.category != "entree"]
        d = kit.start
        while d <= kit.end:
            n = per_day * (1.2 if d.weekday() in (4, 5) else 1.0)
            n = max(0, round(rng.gauss(n, max(1.0, n * 0.12))))
            for _ in range(n):
                hour = rng.choices(hours, weights)[0]
                day = d if hour >= int(o_s[:2]) else d + timedelta(days=1)
                placed = datetime.combine(day, time(hour, rng.randint(0, 59)), zone)
                dp = daypart_for(hour)
                n_lines = rng.choices([1, 2, 3, 4, 5], [25, 30, 25, 12, 8] if dp == Daypart.DINNER
                                      else [40, 32, 18, 7, 3])[0]
                lines = []
                for li in range(n_lines):
                    m = rng.choice(entrees) if li == 0 or rng.random() < 0.35 else rng.choice(others)
                    qty = rng.choices([1, 2, 3], [75, 20, 5])[0]
                    chosen = []
                    for mod in m.available_modifiers:
                        p = spec.modifier_rate(mod, day, rng) if spec.modifier_rate else 0.15
                        if rng.random() < p:
                            chosen.append(mod)
                    lines.append((m, qty, chosen))
                raw.append(dict(spec=spec, store_id=sid, tz=tz, placed_at=placed.astimezone(ZoneInfo("UTC")),
                                local_date=day, local_hour=hour, weekday=day.weekday(), daypart=dp,
                                lines=lines, item_count=sum(q for _, q, _ in lines)))
            d += timedelta(days=1)

    raw.sort(key=lambda r: (r["placed_at"], r["store_id"]))
    cxl_labels = list(CancellationCategory)
    pending_claims = []  # (claim dict, signal)
    signal_ids = {s.store[0]: [] for s in specs}

    for r in raw:
        spec, sid = r["spec"], r["store_id"]
        oid = next_id("ORD", 6)
        subtotal = sum(m.price * q for m, q, _ in r["lines"])
        r["order_id"] = oid

        cancel = spec.cancel_rule(r, rng, kit) if spec.cancel_rule else None
        if cancel is None and rng.random() < kit.base_cancel_rate:
            cancel = (rng.choices(cxl_labels, [35, 30, 10, 10, 15])[0], None, False)
        if cancel and cancel[0] == CancellationCategory.ITEM_OUT_OF_STOCK and cancel[1] is None:
            cancel = (cancel[0], rng.choice(r["lines"])[0].item_id, cancel[2])

        minutes = spec.delivery_minutes(r, rng) if spec.delivery_minutes else rng.randint(25, 55)
        delivered = None if cancel else r["placed_at"] + timedelta(minutes=minutes)
        order = Order(order_id=oid, store_id=sid, customer_ref=rng.choice(customers[sid]),
                      placed_at=r["placed_at"], delivered_at=delivered,
                      status=OrderStatus.CANCELED if cancel else OrderStatus.DELIVERED,
                      daypart=r["daypart"], item_count=r["item_count"], subtotal=subtotal)
        out.orders.append(order)
        r["order"] = order
        for m, q, mods in r["lines"]:
            out.order_items.append(OrderItem(order_id=oid, item_id=m.item_id, quantity=q, modifiers=mods))

        if cancel:
            cxl = Cancellation(evidence_id=next_id("EV-CXL", 6), order_id=oid, store_id=sid, item_id=cancel[1],
                               cancellation_category=cancel[0],
                               canceled_at=r["placed_at"] + timedelta(minutes=rng.randint(3, 20)))
            out.cancellations.append(cxl)
            if cancel[2]:
                signal_ids[sid].append(cxl.evidence_id)
            continue

        new = (spec.claim_rule(r, rng, kit) if spec.claim_rule else []) or kit.generic_claim(r, rng)
        for c in new:
            pending_claims.append((claim_row(c, order, delivered + timedelta(minutes=rng.randint(10, 180)), rng), c.signal))

    for spec in specs:
        if spec.after:
            claimed = {row["order_id"] for row, _ in pending_claims}
            pending_claims += spec.after(raw, customers, claimed, rng, kit)

    # Claim evidence IDs in time order, as in C-01
    pending_claims.sort(key=lambda x: (x[0]["reported_at"], x[0]["order_id"]))
    for row, signal in pending_claims:
        claim = MIClaim(evidence_id=next_id("EV-CLM", 6), **row)
        out.claims.append(claim)
        if signal:
            signal_ids[claim.store_id].append(claim.evidence_id)

    # Operational events, then the labels
    for spec in specs:
        sid, tz = spec.store[0], spec.store[3]
        cause_events = []
        for etype, start, end, desc, is_cause in sorted(spec.events, key=lambda e: e[1]):
            ev = OperationalEvent(
                evidence_id=next_id("EV-EVT", 6), store_id=sid, event_type=etype,
                started_at=local_dt(tz, *start).astimezone(ZoneInfo("UTC")),
                ended_at=local_dt(tz, *end).astimezone(ZoneInfo("UTC")) if end else None, description=desc)
            out.events.append(ev)
            if is_cause:
                cause_events.append(ev.evidence_id)
        cause_day, cause_hour = spec.cause_started
        out.golden.append(GoldenScenario(
            store_id=sid, cause_started_at=local_dt(tz, cause_day, cause_hour).astimezone(ZoneInfo("UTC")),
            key_evidence_ids=cause_events + sorted(signal_ids[sid]), **spec.golden,
        ))
    return out


def claim_row(c: Claim, order: Order, reported: datetime, rng) -> dict:
    pending = c.label == ReviewLabel.PENDING
    return dict(
        order_id=order.order_id, store_id=order.store_id,
        item_id=c.item.item_id if c.item else None, item_name=c.item.name if c.item else "Entire order",
        error_category=c.category, modifier_detail=c.modifier, customer_comments=c.comment,
        error_charge=c.item.price if c.item else order.subtotal, reported_at=reported, review_label=c.label,
        reviewed_at=None if pending else reported + timedelta(hours=rng.randint(20, 72)),
    )


# ---------------------------------------------------------------------------
# GS-05  STORE-K  inventory
# ---------------------------------------------------------------------------
K_CAUSE = date(2026, 11, 4)  # carne asada runs out most evenings; the item stays on the menu
K_ITEM = "Carne Asada Tacos (3)"
K_COMMENTS = [
    "No tacos in the bag. The carne asada tacos were missing.",
    "Paid for the carne asada tacos and they never came.",
    "Everything else was there but no {item}.",
    "Restaurant left out the tacos again.",
    None,
]


def k_claims(o, rng, kit):
    if o["local_date"] >= K_CAUSE and has_item(o, K_ITEM) and rng.random() < 0.22:
        m = line_item(o, K_ITEM)
        return [Claim(ErrorCategory.MISSING_ITEM, m, None, kit.comment(rng, K_COMMENTS, m.name),
                      kit.label(rng, 0.88, 0.02), signal=True)]
    return []


def k_cancels(o, rng, kit):
    if o["local_date"] >= K_CAUSE and has_item(o, K_ITEM) and rng.random() < 0.08:
        return (CancellationCategory.ITEM_OUT_OF_STOCK, line_item(o, K_ITEM).item_id, True)
    return None


GS_05 = Spec(
    store=("STORE-K", "Casa Lupita Taqueria", "San Antonio", "America/Chicago", "mexican", "10:00", "22:00", 65),
    cause_started=(K_CAUSE, 11),
    golden=dict(
        scenario_id="GS-05", split="dev", cause_category="inventory", true_cause="item_out_of_stock_not_marked",
        expected_outcome="diagnosis", expected_owner="merchant", expected_action="update_item_availability",
        key_evidence=[
            "from Nov 4, missing_item claims concentrate on one item, Carne Asada Tacos (3), in every daypart",
            "item_out_of_stock cancellations for the same item start on the same day",
            "comments say the tacos were missing while the rest of the order arrived",
            "order size and daypart don't matter, unlike a packing problem",
        ],
        distractors=["Nov 2 store downtime (1 hour)", "Nov 4 Horchata price change, the same day the rise starts"],
        notes="The kitchen runs out of carne asada but the item stays available on DoorDash, so orders "
              "go out without it. Owner is the merchant: mark the item unavailable when it runs out.",
    ),
    events=[
        (EventType.STORE_DOWNTIME, (date(2026, 11, 2), 12), (date(2026, 11, 2), 13),
         "Store paused on DoorDash for about 1 hour (tablet restart).", False),
        (EventType.MENU_CHANGE, (K_CAUSE, 9), None, 'Price change: "Horchata" from $3.49 to $3.99.', False),
    ],
    claim_rule=k_claims,
    cancel_rule=k_cancels,
)


# ---------------------------------------------------------------------------
# GS-06  STORE-L  Dasher handoff
# ---------------------------------------------------------------------------
L_CAUSE = date(2026, 11, 2)  # pickup shelf moved next to the dine-in counter; Dashers take the wrong bag
L_COMMENTS = [
    "Got someone else's order. The Dasher said all the bags were on one shelf.",
    "The Dasher grabbed the wrong bag, this is not my food.",
    "Driver told me the pickup area moved and he wasn't sure which bag was mine.",
    "Received an order with another customer's name on the receipt.",
    "My order went to someone else, I got theirs.",
    None,
]


def l_claims(o, rng, kit):
    if o["local_date"] >= L_CAUSE and rng.random() < 0.08:
        # The platform first blames the store (store_fault / pending); only some get relabeled
        label = rng.choices([ReviewLabel.STORE_FAULT, ReviewLabel.NOT_STORE_FAULT, ReviewLabel.PENDING],
                            [60, 30, 10])[0]
        return [Claim(ErrorCategory.WRONG_ORDER, None, None, kit.comment(rng, L_COMMENTS), label, signal=True)]
    return []


def l_delivery(o, rng):
    # Waits at pickup get longer and more uneven after the move
    return rng.randint(30, 80) if o["local_date"] >= L_CAUSE else rng.randint(25, 55)


GS_06 = Spec(
    store=("STORE-L", "Route 9 Burger Bar", "Columbus", "America/New_York", "american", "11:00", "23:00", 70),
    cause_started=(L_CAUSE, 11),
    golden=dict(
        scenario_id="GS-06", split="dev", cause_category="dasher_handoff", true_cause="pickup_area_bag_mixup",
        expected_outcome="diagnosis", expected_owner="dasher_ops", expected_action="review_dasher_handoff",
        key_evidence=[
            "from Nov 2, wrong_order claims (whole order) rise; kitchen categories stay normal",
            "the rise is spread over every item and daypart, so it is not one dish or shift",
            "comments say the Dasher took the wrong bag or the pickup area moved",
            "about a quarter of these claims were later relabeled not_store_fault",
        ],
        distractors=['Nov 2 menu change adding "Smash Burger Combo", the same day the rise starts'],
        notes="Handoff problem at pickup, not a kitchen error. Hand off to Dasher operations; no action "
              "for the merchant.",
    ),
    events=[
        (EventType.MENU_CHANGE, (L_CAUSE, 9), None, 'Added "Smash Burger Combo" to the menu.', False),
    ],
    claim_rule=l_claims,
    delivery_minutes=l_delivery,
)


# ---------------------------------------------------------------------------
# GS-07  STORE-M  fraud cluster
# ---------------------------------------------------------------------------
M_CAUSE = date(2026, 11, 6)
M_RING_SIZE, M_CLAIMS_EACH = 4, 7
M_COMMENTS = [
    "Entire order missing. Nothing arrived. Refund everything.",
    "Entire order missing, nothing arrived, refund everything please.",
    "Nothing arrived. Entire order missing. Full refund.",
]


def m_ring(raw: list, customers: dict, claimed: set, rng, kit):
    """Four customer_refs place repeat orders from Nov 6 and claim every one as missing. All still pending."""
    zone = ZoneInfo("America/Los_Angeles")
    pool = sorted(
        (r["order"] for r in raw
         if r["store_id"] == "STORE-M" and r["order"].status == OrderStatus.DELIVERED
         and r["local_date"] >= M_CAUSE and r["order"].order_id not in claimed),
        key=lambda o: o.order_id,
    )
    ring = rng.sample(customers["STORE-M"], M_RING_SIZE)
    rows = []
    for o in rng.sample(pool, M_RING_SIZE * M_CLAIMS_EACH):
        o.customer_ref = ring[len(rows) % M_RING_SIZE]
        reported = o.delivered_at + timedelta(minutes=rng.randint(5, 40))
        if reported.astimezone(zone).date() > kit.end:
            reported = o.delivered_at + timedelta(minutes=5)
        rows.append((claim_row(Claim(ErrorCategory.MISSING_ITEM, None, None, rng.choice(M_COMMENTS),
                                     ReviewLabel.PENDING), o, reported, rng), True))
    return rows


GS_07 = Spec(
    store=("STORE-M", "Hikari Ramen", "Portland", "America/Los_Angeles", "japanese", "11:00", "22:00", 60),
    cause_started=(M_CAUSE, 11),
    golden=dict(
        scenario_id="GS-07", split="dev", cause_category="fraud_cluster", true_cause="refund_abuse_ring",
        expected_outcome="diagnosis", expected_owner="fraud_review", expected_action="send_to_fraud_review",
        key_evidence=[
            "from Nov 6, four customer_refs file 7 'Entire order' claims each, all still pending",
            "fraud_signals flags all four customer_refs",
            "near-identical comments and full-order refunds",
            "without these four customers the store's rate stays normal",
        ],
        distractors=["Nov 5 POS app update, the day before the rise"],
        notes="Refund abuse, not a store problem. Send to fraud review; no action for the merchant.",
    ),
    events=[
        (EventType.POS_CHANGE, (date(2026, 11, 5), 8), None, "POS tablet app updated to a new version.", False),
    ],
    after=m_ring,
)

DEV_SPECS = [GS_05, GS_06, GS_07]

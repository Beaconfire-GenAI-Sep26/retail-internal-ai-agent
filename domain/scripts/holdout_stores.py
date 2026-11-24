"""HOLDOUT scenario stores (C-04): STORE-N, STORE-O, STORE-P.

Final evaluation only. Keep this file out of the repository until B-05's final run, so the agent's
prompts are never tuned on these stores. reset_and_seed loads it only with --holdout:

    python -m domain.scripts.reset_and_seed --holdout

The stores are generated after the dev stores, so every dev row and ID is the same with or without them.
"""
from datetime import date

from domain.app.models import CancellationCategory, Daypart, ErrorCategory, EventType, ReviewLabel
from domain.scripts.scenario_stores import Claim, Spec

HOLDOUT_SEED = 24 + 3


# ---------------------------------------------------------------------------
# GS-08  STORE-N  two causes at once: a POS modifier (main) and dinner packing (second)
# ---------------------------------------------------------------------------
N_POS_CAUSE = date(2026, 10, 28)  # POS re-sync drops the "Add guacamole" ticket line
N_PACK_CAUSE = date(2026, 11, 5)  # new dinner crew; large orders lose a bag
N_GUAC_COMMENTS = [
    "Paid for guacamole on the {item}, there was none.",
    "No guac in my burrito even though I added it.",
    "Guacamole add-on was charged but missing.",
    None,
]
N_BAG_COMMENTS = [
    "Only one of our two bags came. Drinks and sides missing.",
    "Second bag never arrived, missing the {item} and more.",
    None,
]


def n_modifier_rate(mod, day, rng):
    return 0.35 if mod == "Add guacamole" else 0.15


def n_claims(o, rng, kit):
    out = []
    if o["local_date"] >= N_POS_CAUSE:
        for m, _, mods in o["lines"]:
            if "Add guacamole" in mods and rng.random() < 0.25:
                out.append(Claim(rng.choice([ErrorCategory.INGREDIENT_ERROR, ErrorCategory.INCORRECT_ITEM]), m,
                                 "Add guacamole", kit.comment(rng, N_GUAC_COMMENTS, m.name),
                                 kit.label(rng, 0.90, 0.02), signal=True))
                break
    if (o["local_date"] >= N_PACK_CAUSE and o["daypart"] == Daypart.DINNER and o["item_count"] >= 5
            and rng.random() < 0.25):
        bag = [m for m, _, _ in o["lines"] if m.category in ("drink", "dessert", "side")] or [o["lines"][-1][0]]
        out.append(Claim(ErrorCategory.MISSING_ITEM, bag[0], None, kit.comment(rng, N_BAG_COMMENTS, bag[0].name),
                         kit.label(rng, 0.88, 0.02)))  # second cause: not in key_evidence_ids
    return out


GS_08 = Spec(
    store=("STORE-N", "Verde Burrito Co", "Austin", "America/Chicago", "mexican", "10:00", "22:00", 70),
    cause_started=(N_POS_CAUSE, 10),
    golden=dict(
        scenario_id="GS-08", split="holdout", cause_category="pos_modifier_mapping",
        true_cause="pos_modifier_not_mapped_plus_dinner_packing",
        expected_outcome="diagnosis", expected_owner="pos_team", expected_action="fix_modifier_mapping",
        key_evidence=[
            "from Oct 28, ingredient_error / incorrect_item claims with modifier_detail 'Add guacamole', all dayparts",
            "Oct 28 POS menu re-sync",
            "a second, smaller group from Nov 5: missing_item on dinner orders with 5+ items, comments about a missing bag",
        ],
        distractors=["Nov 3-9 promotion raising volume"],
        notes="Two causes. Main: the Add guacamole modifier is not printed on the kitchen ticket after the "
              "Oct 28 POS re-sync (scored). Second: dinner packing from Nov 5 (add_large_order_bag_check, "
              "merchant); a good result names it as a second finding or a follow-up. Only the main cause is scored.",
    ),
    events=[
        (EventType.POS_CHANGE, (N_POS_CAUSE, 9), None, "POS menu re-synced after a modifier list update.", True),
        (EventType.PROMOTION, (date(2026, 11, 3), 0), (date(2026, 11, 10), 0), "Promotion: free chips with any burrito (Nov 3-9).", False),
    ],
    modifier_rate=n_modifier_rate,
    claim_rule=n_claims,
)


# ---------------------------------------------------------------------------
# GS-09  STORE-O  conflicting, thin evidence: the right answer is unsure
# ---------------------------------------------------------------------------
O_START = date(2026, 11, 7)


def o_claims(o, rng, kit):
    if o["local_date"] >= O_START and rng.random() < 0.045:
        cat = rng.choice(list(ErrorCategory))
        m, _, mods = rng.choice(o["lines"])
        label = rng.choice([ReviewLabel.PENDING, ReviewLabel.STORE_FAULT])  # half still unreviewed
        if cat == ErrorCategory.WRONG_ORDER:
            return [Claim(cat, None, None, None, label)]
        comment = kit.comment(rng, kit.generic_comments[cat], m.name) if rng.random() < 0.3 else None
        return [Claim(cat, m, rng.choice(mods) if mods and rng.random() < 0.3 else None, comment, label)]
    return []


GS_09 = Spec(
    store=("STORE-O", "Harvest Table Salads", "Minneapolis", "America/Chicago", "healthy", "10:00", "21:00", 55),
    cause_started=(O_START, 10),
    golden=dict(
        scenario_id="GS-09", split="holdout", cause_category="other", true_cause="no_single_cause_in_data",
        expected_outcome="unsure", expected_owner="analyst", expected_action="analyst_review",
        key_evidence=[
            "from Nov 7 the rate rises to about 5%, spread over every item, daypart, order size and category",
            "about half of the new claims are still pending review and most have no comment",
            "no operational event lines up with Nov 7",
        ],
        distractors=["Oct 25 menu change (unrelated, two weeks earlier)"],
        notes="Nothing in the data separates a cause. A good result says unsure, lists what it ruled out, "
              "and hands the case to an analyst instead of guessing.",
    ),
    events=[
        (EventType.MENU_CHANGE, (date(2026, 10, 25), 9), None, 'Added "Harvest Grain Bowl" to the menu.', False),
    ],
    claim_rule=o_claims,
)


# ---------------------------------------------------------------------------
# GS-10  STORE-P  POS modifier again, new store, item, modifier and date (tests memorizing GS-01)
# ---------------------------------------------------------------------------
P_CAUSE = date(2026, 11, 5)
P_COMMENTS = [
    "Added jalapenos to the {item} and there were none.",
    "Paid extra for jalapenos, pizza came without them.",
    "Jalapenos missing again on my pizza.",
    None,
]


def p_modifier_rate(mod, day, rng):
    if mod == "Add jalapenos":
        return 0.40 if day >= P_CAUSE else 0.0
    return 0.15


def p_claims(o, rng, kit):
    if o["local_date"] >= P_CAUSE:
        for m, _, mods in o["lines"]:
            if "Add jalapenos" in mods and rng.random() < 0.22:
                return [Claim(rng.choice([ErrorCategory.INGREDIENT_ERROR, ErrorCategory.INCORRECT_ITEM]), m,
                              "Add jalapenos", kit.comment(rng, P_COMMENTS, m.name), kit.label(rng, 0.90, 0.02),
                              signal=True)]
    return []


def p_cancels(o, rng, kit):
    if o["weekday"] in (4, 5) and o["daypart"] == Daypart.DINNER and rng.random() < 0.10:
        return (CancellationCategory.TOO_BUSY, None, False)
    return None


GS_10 = Spec(
    store=("STORE-P", "Brick Lane Pizza", "Philadelphia", "America/New_York", "italian", "11:00", "23:00", 75),
    cause_started=(P_CAUSE, 10),
    golden=dict(
        scenario_id="GS-10", split="holdout", cause_category="pos_modifier_mapping",
        true_cause="pos_modifier_not_mapped",
        expected_outcome="diagnosis", expected_owner="pos_team", expected_action="fix_modifier_mapping",
        key_evidence=[
            "from Nov 5, ingredient_error / incorrect_item claims with modifier_detail 'Add jalapenos' on pizzas",
            "Nov 5 menu change adding the Add jalapenos modifier",
        ],
        distractors=["Nov 5 store downtime (2 hours), the same day", "weekend dinner too_busy cancellations"],
        notes="Same pattern as GS-01 with a different store, item, modifier and date.",
    ),
    events=[
        (EventType.MENU_CHANGE, (P_CAUSE, 10), None, 'Added paid modifier "Add jalapenos" (+$1.49) to pizzas.', True),
        (EventType.STORE_DOWNTIME, (P_CAUSE, 17), (P_CAUSE, 19), "Store paused on DoorDash for about 2 hours (oven repair).", False),
    ],
    added_modifiers={"Margherita Pizza": ["Add jalapenos"], "Pepperoni Pizza": ["Add jalapenos"]},
    modifier_rate=p_modifier_rate,
    claim_rule=p_claims,
    cancel_rule=p_cancels,
)

HOLDOUT_SPECS = [GS_08, GS_09, GS_10]

# C-05: what each holdout store's mock merchant answers to a dispatched question
HOLDOUT_INBOX = {
    "STORE-N": "Our POS menu was re-synced at the end of October. Guacamole is still on the menu as an add-on.",
    "STORE-O": "We haven't changed anything lately that we know of. Same staff, same menu.",
    "STORE-P": "We started offering jalapenos as an add-on for pizzas in early November.",
}

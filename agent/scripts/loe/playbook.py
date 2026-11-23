"""LOE checklist: the standard operating procedure for one store-level M&I case.

The same steps run in the same order on every case and leave findings as flags. One decision table turns them into a
cause, a level and, where one answer would settle it, a question. Every tool call is one check.

 1. Size and date it: the day with the strongest lasting step up, and the claims since then above the store's normal
    rate. The 7-day window only says when it was noticed. (LOE sizes a problem from order-level data.)
 2. Split the extra claims by review label and error type, before against after. (Who is at fault decides who pays.)
 3. Screen for fraud: flagged refs hold most of the extra claims while store_fault claims alone stay near normal.
    (Fraudulent reports are never the store's fault, so they go before any store fix is discussed.)
 4. Segment the error types that rose by item, modifier, daypart and order size. (LOE spots patterns in order data.)
 5. Read the events. (A nearby event is a lead: its type says what changed, not what went wrong.)
 6. Name the group that carries the rise: a modifier, a few items, missing items of many kinds (bag), swapped orders,
    a busy shift, or none. 7. Follow it by day, by daypart, each of its items by order size, and before against after
    with the rest of the store as control. (An attribution has to rest on records someone can check.)
 8. Check stock-out cancellations of the affected items. (Marking items out of stock is a standard fix.)
 9. Ask the merchant one question when its answer separates causes these checks can't. (LOE works with merchants.)
10. Decide with the table. High and medium send the catalog fix. Low hands the leading cause to the analyst, because
    a wrong fix keeps the rate up for another 7 to 14 days.

Confidence: a table row states the level the checks support alone. A reply that confirms the row's cause adds a level;
one that points to another open cause gives medium; one that contradicts what was measured (CLASH) sends nothing, as
platform data win. A denial helps only where it leaves one cause. A level comes off when the rest of the store rose too,
under FEW_CLAIMS records show the pattern or the rise is within TEST_Z standard errors of normal. High becomes medium
when most records are pending, and for a handoff, which platform data can't test.

What it can't do: it works one leading problem, so a second one is at most a gap. Without an answer it can't tell a lost
bag from short packing unless add-ons stand out, or a young ticket fault from a crew still learning or a steady shortage,
so those go to the analyst. It never sends a fix for wrong orders or "other" on its own. It can't see through a merchant
who is wrong about something platform data doesn't show. Fraud by refs under the flag bar isn't recognized.

Thresholds and their reasons:
 STEP_GAIN 4.5: log-likelihood gain of a dated step, about 1 in 20 by chance after trying every day of six weeks.
 MIN_AFTER_DAYS 3: one or two bad days can be chance. WEEK 7: covers every weekday; under one shows no trend.
 TWO_WEEKS 14: DoorDash's own horizon, long enough for staff to learn. FOUR_WEEKS 28: the monitor's baseline.
 HEALTHY_RATE 2.25%: the published target, used only when the data has no clean period before the rise.
 MIN_CLAIMS 5, FEW_CLAIMS 10: under five is noise; under ten is too few to judge a trend or send a fix on.
 SCAN_Z 3, TEST_Z 2, NO_SLIDE 1: standard errors for a scan of many groups or days, for one planned comparison, and
   under which a trend shows no sign of falling back.
 TWICE 2, RAISED 1.5, LEVEL 1.25: rates rarely double by chance, so a fade must halve; within a quarter is level.
 HALF 0.5: a group explains a rise when it holds half of it; a control that moved half as much moved with it.
 NAMED 0.4: the same bar for a modifier, a little lower because not every claim names its modifier.
 MOSTLY 0.65, RISEN 0.2: two thirds of the extra claims is "mostly"; a fifth is a real part of the rise.
 COLD 0.25: a daypart at a quarter of the group's rate is not affected.
 EVENT_SLACK 2, NAME_MATCH 0.6: dating error and time zones; most words of a menu name are in the event text.
 STRAY 3: more than two stray stock-outs or comments, and three times the average item's stock-outs.
 SHORT_REPLY 6 words: a longer reply says more than yes or no, so a bare yes or no in it is no answer.
"""
from __future__ import annotations

import re
from collections import Counter, namedtuple
from datetime import date, timedelta
from math import log, sqrt
from typing import Any

from agent.scripts.loe.tools import Case, Conclusion, Question, Reply, RuledOut, ToolResult, counts, groups, value

STEP_GAIN, MIN_AFTER_DAYS, WEEK, TWO_WEEKS, FOUR_WEEKS = 4.5, 3, 7, 14, 28
HEALTHY_RATE = 0.0225
MIN_CLAIMS, FEW_CLAIMS = 5, 10
SCAN_Z, TEST_Z, NO_SLIDE = 3.0, 2.0, 1.0
TWICE, RAISED, LEVEL = 2.0, 1.5, 1.25
HALF, NAMED, MOSTLY, RISEN, COLD = 0.5, 0.4, 0.65, 0.2, 0.25
EVENT_SLACK, NAME_MATCH, STRAY, SHORT_REPLY = 2, 0.6, 3, 6
MAX_CITED = 20  # the most evidence IDs a conclusion may cite

Tools = Any  # the real Tools or the kit's stand-in: the same method names and arguments
Series = list[tuple[date, int, int]]  # day, claims, orders
DAY = timedelta(days=1)
LEVELS = ("low", "medium", "high")
ERROR_TYPES = ("missing_item", "incorrect_item", "ingredient_error", "wrong_order")
POS, MENU, STOCK, PACKING, HANDOFF, FRAUD, OTHER = (
    "pos_modifier_mapping", "menu_change", "inventory", "packing", "dasher_handoff", "fraud_cluster", "other")
ACTIONS = {POS: "fix_modifier_mapping", MENU: "review_menu_change", STOCK: "update_item_availability",
           PACKING: "add_large_order_bag_check", HANDOFF: "review_dasher_handoff", FRAUD: "send_to_fraud_review"}
Event = namedtuple("Event", "evidence_id kind day text")

# --- steps 9 and 10 as data. A row: the group that carries the rise; the flags it needs ("!" must not, "|" or); the
# cause; the level the checks support alone; the question that would settle it; and why. The first row that fits wins.
# Flags: event, menu, named: a menu or POS event is linked to the start, it is a menu_change, its text names the group.
# fading, on_off: the group's days. some: only some dayparts. holds: steady in all dayparts, without stock-outs.
# uneven: none of that. steeper, flat: the same items in large against small orders. stock: stock-outs that match.
# cut: a daypart or order size holds the rise. add_ons: drinks, sides and desserts are left out more than mains.
# mostly, left_out, made_wrong: error types. whole: whole orders or bags went astray. week, two_weeks: days seen.
Row = namedtuple("Row", "kind needs cause level ask why")
TABLE = (
    Row("fraud", "", FRAUD, "high", "", "Flagged refs hold most of it, and store_fault claims alone did not rise."),
    Row("modifier", "stock !event", STOCK, "medium", "supply", "Stock-outs of items that offer it point to supply."),
    Row("modifier", "menu named fading", MENU, "medium", "ticket", "They start with a menu event and fade as staff learn."),
    Row("modifier", "holds named two_weeks", POS, "high", "", "They start with an event and hold for two weeks."),
    Row("modifier", "holds two_weeks | holds event week !menu", POS, "medium", "ticket",
        "They hold across days and dayparts, as a fault in the ticket would."),
    Row("modifier", "holds", POS, "low", "ticket", "They hold so far, as would a crew's mistakes or a steady shortage."),
    Row("modifier", "uneven !event", STOCK, "low", "supply", "They come and go, and no event starts them."),
    Row("modifier", "", POS, "low", "ticket", "The days since the start are too few or too uneven to judge."),
    Row("item", "stock !event !steeper", STOCK, "high", "", "Stock-outs of the item match, and no event starts it."),
    Row("item", "stock", STOCK, "medium", "stock", "Stock-out cancellations of the same item match the claims."),
    Row("item", "menu named made_wrong !on_off", MENU, "high", "", "A menu event on it starts them; it is made wrong."),
    Row("item", "menu named !steeper !on_off", MENU, "medium", "stock", "A menu event on it starts them, without stock-outs."),
    Row("item", "!event steeper left_out", PACKING, "medium", "stock",
        "The same item is missed far more often in large orders, which fits short packing, not short supply."),
    Row("item", "!event flat one_item on_off !made_wrong | !event flat one_item some !made_wrong", STOCK, "medium",
        "stock", "The item goes wrong as often in small as in large orders, and only on some days or dayparts."),
    Row("item", "", STOCK, "low", "stock", "The checks don't separate supply from packing or a menu cause."),
    Row("bag", "stock | few_items !steeper", STOCK, "low", "stock", "A few items hold most of it, so supply fits too."),
    Row("bag", "cut mostly add_ons !whole", PACKING, "medium", "bags",
        "Drinks, sides or desserts are left out more than mains, mostly where orders are largest or busiest."),
    Row("bag", "", PACKING, "low", "bags", "Items of many kinds are missed, and packing and the handoff both fit."),
    Row("swap", "", HANDOFF, "low", "pickup", "Most of the rise is whole orders that belonged to someone else."),
    Row("shift", "", OTHER, "medium", "", "Error types are mixed and spread over the menu, as in a busy kitchen."),
    Row("none", "", None, "low", "", "No item, modifier, daypart or order size holds half of the extra claims."),
)
CLASH = {POS: "stock | fading | on_off | some", MENU: "stock | !menu | holds two_weeks", HANDOFF: "stock | add_ons",
         STOCK: "steeper | spread_out | holds event | holds two_weeks", PACKING: "stock | flat"}  # measured otherwise
QUESTIONS = {  # the question, and why the analyst should send it
    "ticket": ("Since {day}, orders with {name} keep coming out wrong or without it. When that choice is ordered, "
               "does it print on the kitchen ticket?", "Platform data can't show what reaches the kitchen ticket."),
    "supply": ("Since {day}, orders with {name} come out wrong or without it on some days. Does that choice print on "
               "the kitchen ticket, and did the kitchen run out of what it needs?", "Neither shows in platform data."),
    "stock": ("Since {day}, {name} came missing or wrong in more orders than usual. Did the kitchen run out of it, "
              "or of something it needs, while it could still be ordered?",
              "Only the merchant knows whether the item ran out, was left out of the bag or is made in a new way."),
    "bags": ("Since {day}, items are missing more often from {name}. How are those orders bagged and checked, and do "
             "staff hand every bag to the Dasher or do Dashers pick up from a shelf or counter?",
             "Platform data has no bag or Dasher records, so it can't separate packing from the handoff."),
    "pickup": ("Since {day}, more {name} turn out to be someone else's. How do bags reach the Dasher: do staff check "
               "the name and hand them over, or do Dashers pick up from a shelf or counter?",
               "Swapped orders can start at the packing station or at pickup, and only the merchant sees which."),
}
OPEN = {"ticket": {POS, MENU, STOCK}, "supply": {POS, MENU, STOCK}, "stock": {STOCK, PACKING, MENU},
        "bags": {PACKING, HANDOFF}, "pickup": {HANDOFF, PACKING}}  # the causes each question tells apart


def fits(needs: str, flags: set[str]) -> bool:
    """Whether the flags meet one of the alternatives in `needs`."""
    return any(all((n[1:] not in flags) if n[0] == "!" else n in flags for n in option.split())
               for option in needs.split("|"))


# --- small statistics

def totals(series: Series, start: date = date.min, end: date = date.max) -> tuple[int, int]:
    """Claims and orders from start up to, not including, end."""
    span = [x for x in series if start <= x[0] < end]
    return sum(k for _, k, _ in span), sum(n for _, _, n in span)


def tally(rows: list[Any], names: list[str], inside: bool = True) -> tuple[int, int]:
    """Claims and orders of the named breakdown groups, or of all the others."""
    chosen = [g for g in rows if g.orders and (g.name in names) == inside]
    return sum(g.claims for g in chosen), sum(g.orders for g in chosen)


def step_day(series: Series) -> date | None:
    """First day of the strongest lasting step up (binomial log-likelihood), or None when no step is clear."""
    def fit(k: int, n: int) -> float:
        return k * log(k / n) + (n - k) * log(1 - k / n) if 0 < k < n else 0.0

    best, found = STEP_GAIN, None
    for day, _, _ in series[WEEK:len(series) - MIN_AFTER_DAYS + 1]:
        (k0, n0), (k1, n1) = totals(series, end=day), totals(series, day)
        gain = fit(k0, n0) + fit(k1, n1) - fit(k0 + k1, n0 + n1)
        if n0 and n1 and k1 / n1 > k0 / n0 and gain > best:
            best, found = gain, day
    return found


def versus(k1: int, n1: int, k0: int, n0: int) -> str:
    """One planned comparison of two rates: the first is higher, the same (within a quarter), or it's unclear."""
    if not n1 or not n0 or k1 + k0 < FEW_CLAIMS:
        return "unclear"
    p = min((k1 + k0) / (n1 + n0), 0.99)
    gap = (k1 / n1 - k0 / n0) / sqrt(p * (1 - p) * (1 / n1 + 1 / n0))
    if k1 / n1 >= RAISED * k0 / n0 and gap >= TEST_Z:
        return "higher"
    return "same" if k1 / n1 <= LEVEL * k0 / n0 else "unclear"


def shape_of(days: Series) -> str:
    """How the rate moves since the start: steady, fading (a clear slide to half), on_off, or unclear."""
    sold = [x for x in days if x[2]]
    (k, n), half = totals(sold), len(sold) // 2
    if len(sold) < WEEK - 1 or k < FEW_CLAIMS:
        return "unclear"
    (k1, n1), (k2, n2), p = totals(sold[:half]), totals(sold[half:]), min(k / n, 0.99)
    middle = sum(i * m for i, (_, _, m) in enumerate(sold)) / n
    slide = sum((i - middle) * (x - p * m) for i, (_, x, m) in enumerate(sold))  # Cochran-Armitage trend
    slide /= sqrt(p * (1 - p) * sum(m * (i - middle) ** 2 for i, (_, _, m) in enumerate(sold)))
    swing = sum((x - p * m) ** 2 / (p * (1 - p) * m) for _, x, m in sold) - (len(sold) - 1)  # chi-square over days
    swing /= sqrt(sum(2 + 1 / (p * m) for _, _, m in sold))
    if slide <= -TEST_Z and k1 / n1 >= TWICE * k2 / n2:
        return "fading"
    return "on_off" if swing >= SCAN_Z else "steady" if slide > -NO_SLIDE and swing < TEST_Z else "unclear"


def spread_of(rows: list[Any]) -> tuple[str, list[str]]:
    """Whether the dayparts with enough orders, most of its orders, are all hit, or only some (and which)."""
    k, n = tally(rows, [], False)
    fair = [g for g in rows if n and g.orders and k * g.orders / n >= MIN_CLAIMS]
    cold = [g.name for g in fair if g.claims <= COLD * k * g.orders / n]
    if cold:
        return "some", sorted(g.name for g in rows if g.claims and g.name not in cold)
    return ("all" if n and sum(g.orders for g in fair) >= MOSTLY * n else "unclear"), []


# --- text: dates, quoted names and event links

BLOCKED = re.compile(  # words the content policy could stop once a menu name stands in one of our sentences
    r"http|www|@|cust-|\d[\d\s().-]{6,}\d|\.(com|net|org)|refund|credit|charg|penal|\b(fine|bill)|deactivat|suspend"
    r"|disabl|delist|offboard|contact|ignor|disregard|overrid|bypass|skip|instruct|approv|customer|merchant|restaurant"
    r"|store|system|developer|menu", re.I)
WHOLE_BAG = re.compile(  # a customer comment about more than one left-out item
    r"(whole|entire|second|other|another|missing|one) bag|bag (was |is )?missing|wrong (bag|order)|someone else"
    r"|half (of )?(my|the|our) (order|food)|dasher|driver|courier", re.I)
ADD_ON = re.compile(r"drink|beverage|soda|juice|coffee|side|dessert|sweet|sauce|dip|snack|extra|add", re.I)
COSMETIC = re.compile(  # news no order goes wrong over
    r"^(?!.*(recipe|replac|renam|modifier|option|ingredient|portion|size|made|build|map|sync)).*\b(pric|photo|picture"
    r"|image|typo|hours)", re.I)


def on(day: date) -> str:
    return f"{'Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec'.split()[day.month - 1]} {day.day}"


def quote(text: str, longest: int) -> str:
    """A menu name as short plain words; a name the content policy could block is left out."""
    plain = " ".join(re.sub(r"[^\w\s&'%+/-]", " ", text).split())
    safe = plain and not BLOCKED.search(text) and not BLOCKED.search(plain)
    return f'"{plain[:longest].rstrip()}"' if safe else "the affected menu choice"


def named(text: str, menu_names: Any) -> bool:
    """Whether the event text contains most words of one of the menu names."""
    def words(s: str) -> set[str]:
        found = {w[:-1] if len(w) > 3 and w.endswith("s") else w for w in re.findall(r"[a-z]{2,}|\d+", s.lower())}
        return found - {"the", "and", "with", "for", "of"}

    return any(len(want & words(text)) >= NAME_MATCH * len(want) for n in menu_names if (want := words(n)))


# --- reading the reply: in each clause the first sign that matches counts. "-" speaks against a cause, and a negation
# shortly before a sign turns it around ("we never forget it", "it doesn't print")

NOT = re.compile(r"\b(not|no|never|nobody|nothing|none|without|rarely|stopped)\b.{0,25}$")
CONTRACTED = re.compile(r"\b(do|does|did|is|was|are|were|has|have|had|could|would|should|ca|wo|ai)n'?t\b")
ANSWER = re.compile(  # a yes or no that answers the question, not "no changes here"
    r"(yes|yeah|yep|no|nope|nah)\b(?=\s*($|[,.!;:-]|(it|they|that|we|i|the|our|its|it's|every|all|always|not|never)\b))")
TICKET = r"(ticket|chit|kds|screen|slip|printer|printout|receipt|display)s?\b"
NO_FAULT = (r"^(?=.*(print|ticket|slip|chit|\bpos\b|system|register))(?=.*\b(no|not|nothing)\b.{0,20}\b(problem|issue"
            rf"|trouble|wrong|missing|fault))|not (the|our) (\w+ )?(pos|system|register|{TICKET})")
BROKEN = (rf"{TICKET}.{{0,40}}\b(missing|blank|wrong|drop\w*|broken|glitch\w*|just|only)\b|\b(missing|gone|drop\w*"
          rf"|left off)\b.{{0,25}}\b{TICKET}|\b(only|just) (say|show|print|list)s?\b|\bonly\b.{{0,30}}\b{TICKET}"
          r"|used to print|print\w*\b.{0,15}?\b(wrong|blank|different|as)\b|not (\w+ )?(mapp|link|sync)"
          r"|^ ?not the (add|option|modif|extra|choice)")
PRINTS = (rf"\bprint(s|ed|ing)?\b|\bshow|appear|com(e|es|ing) (up|through|thru|out|over)|\b(on|to|reach\w*) (the|our"
          rf"|any|every|each|all|that) (\w+ )?{TICKET}|{TICKET} (has|have|list|say)|\bon (there|it)\b|\bsee(s|ing)? it\b"
          r"|(kitchen|cook|line|crew).{0,12}\b(see|get)s?\b")
LEARNING = (r"(not |never )(\w+ ){0,2}(trained|learned|learnt)|train|learn|recipe|habit|confus|old (way|version|one)"
            r"|(\w+ ){0,3}(the hang of|familiar|used to (it|them|the|this))|get\w* it wrong|new (\w+ )?(crew|staff|hire"
            r"|cook|people|team|shift|version|guy|kid)|not (\w+ )?(notic|told|aware|read|look|(do|mak)ing \w+ right)")
FORGET = r"forg[eo]t\w*(?! to (mark|turn|take|switch|flag|86|pull|update))|overlook"
SHORT = (r"\br[au]n\w* (\w+ )?(out|low|short)\b(?! of (time|staff|people|hands|bags))|(sold|sell|selling) out|\b86"
         r"|out of (it|them|stock|that|those|this|the)\b|(is|was|were|are|been|be|got|'re|'m|'s) (all )?out\b"
         r"|(?<!staff )shortage|shorted|short on (?!staff|people|time)|not enough (?!staff|people|time|hands)"
         r"|not (\w+ )?(have|get|got|deliver) (any|enough|it in)|had none|no (stock|more)|low on|supplier")
STOCKED = r"plenty|\bin stock|(always|still) (have|had)|had (lots|enough)|(fully|well) stocked|not (\w+ )?short (of|on)"
PACK = (rf"{FORGET}|(get|got|gets|getting) left|left out|leav\w+ (\w+ )?out|miss(es|ed)\b|miss(ing)? (stuff|items?"
        r"|things?|it|anything|some)|separate|second bag|one person|mislabel|short.?(staff|hand)|mix\w* up|on us\b"
        r"|our (fault|mistake|bad)|new (\w+ )?(bagger|packer|person|hire|crew|staff|kid|guy)|wrong (label|receipt"
        r"|sticker)|into? the wrong bag|not make it|pack\w* wrong")
DRIVER = r"(dasher|driver|courier|delivery (guy|person|people))s?\b"
CLEARED = rf"not (the |our |a )?{DRIVER}|{DRIVER} (is|are) (not (the|our|at)|fine|ok|good)"
TAKEN = (rf"{DRIVER}.{{0,60}}?\b(grab|tak\w+|took|pick|leav\w+|left|forg\w+|mix|swap|wrong|walk|rush|not check)"
         rf"|(it's|its|is) (all |just )?the {DRIVER}|after (they |it |the )?(pick|leaves)|after {DRIVER} le"
         r"|(left|leav\w+|sit\w*|put|pick\w*|grab\w*|tak\w+|took)\b.{0,30}?\b(shelf|shelves|counter|rack|behind)"
         r"|unattended|self.?serve|wrong (dasher|driver|courier)|in (the|their) car"
         r"|(grab|took|take|pick|hand|gave|give)\w*\b.{0,25}?\bwrong (bag|order|one)")
HANDED = r"(hand|give|gave|pass)\w*\b.{0,40}?\b(dasher|driver|courier|over)|hand (it|them|every|each|all)"
NAME_CHECK = r"(check|verif|match|confirm|ask)\w*.{0,20}\bname|name.{0,15}(check|verif|match)"  # staff check at pickup
READ = {"ticket": ((NO_FAULT, "-" + POS), (BROKEN, POS), (LEARNING, MENU), (PRINTS, "-" + POS), (STOCKED, "-" + STOCK),
                   (SHORT, STOCK), (rf"{FORGET}|skip|miss(es|ed)? (it|that|this)|keeps? missing|mistake", MENU)),
        "stock": ((STOCKED, "-" + STOCK), (SHORT, STOCK), (LEARNING, MENU), (PACK, PACKING)),
        "bags": ((CLEARED, "-" + HANDOFF), (TAKEN, HANDOFF), (HANDED, "-" + HANDOFF), (PACK, PACKING), (SHORT, STOCK),
                 (r"check|verif|seal|stapl|\bcount(?!er)|label|match", "-" + PACKING)),
        "pickup": ((CLEARED, "-" + HANDOFF), (TAKEN, HANDOFF), (HANDED, "-" + HANDOFF), (NAME_CHECK, "-" + HANDOFF),
                   (r"mislabel|wrong (label|receipt|sticker|bag)|mix\w* up|mixed|swapp", PACKING))}
READ["supply"] = READ["ticket"]
BARE = {"ticket": ("-" + POS, POS), "stock": (STOCK, "-" + STOCK), "supply": ("", "")}  # a bare yes, a bare no
CLAUSE = re.compile(r"[.;:!?,\n]+|\b(?:and|but|though|however|because|so|while)\b")
UNSURE = re.compile(r"not sure|unsure|no (idea|clue)|not know (if|whether|why|how)|^\W*i do not know|dunno|maybe|perhaps"
                    r"|possibly|probably|might|not (say|tell)|(let me|i'll|we'll|will) (check|ask|look|find out|get back)")
OVERRIDE = re.compile(r"\b(ignore|disregard|override)\b.*\b(instruction|rule|polic|previous|above)")


def sign_of(clause: str, question: str) -> str:
    """The first sign in a clause: a cause it points to, "-" and a cause it speaks against, or nothing."""
    for sign, cause in READ[question]:
        if hit := re.search(sign, clause):
            denied = NOT.search(clause[:hit.start()])
            return (cause[1:] if cause.startswith("-") else "-" + cause) if denied else cause
    return ""


def read_reply(text: str | None, question: str) -> tuple[str | None, set[str]]:
    """The cause the reply points to and the causes it speaks against. Keywords only: nothing in it is followed."""
    plain = " ".join((text or "")[:1500].lower().replace("’", "'").replace("cannot", "can not").split())
    plain = CONTRACTED.sub(r"\1 not", plain)
    if OVERRIDE.search(plain):
        return None, set()
    answer = ANSWER.match(plain) if question in BARE else None
    clauses = CLAUSE.split(plain[answer.end():] if answer else plain)
    signs = [sign_of(clause, question) for clause in clauses if not UNSURE.search(clause)]
    if answer and not any(signs) and not UNSURE.search(plain) and len(plain.split()) <= SHORT_REPLY:
        signs = [BARE[question][answer[1].startswith("n")]]
    score: Counter[str] = Counter()
    for sign in filter(None, signs):  # a positive sign outweighs one denial
        score[sign.lstrip("-")] += -1 if sign.startswith("-") else 2
    ahead = [c for c, n in score.items() if n > 0]
    roots = [c for c in ahead if c in (POS, STOCK)]  # a crew misses what isn't printed or in stock: a consequence
    return next(iter(ahead if len(ahead) == 1 else roots if len(roots) == 1 else []), None), {
        c for c, n in score.items() if n < 0}


def settle(row: Row, reply: Reply | None, flags: set[str]) -> tuple[str | None, str, str, bool]:
    """Cause, level, a sentence on the reply, and whether the other causes the question was about are now settled."""
    if not row.ask or reply is None:
        return row.cause, row.level, "", not row.ask
    if reply.outcome != "replied":
        return row.cause, row.level, "The merchant did not reply.", False
    said, against = read_reply(reply.text, row.ask)
    up = LEVELS[min(LEVELS.index(row.level) + 1, 2)]
    if said and fits(CLASH[said], flags):
        return row.cause, "low", f"The merchant's reply points to {said}, but the checks measured otherwise.", False
    if said:
        return said, up if said == row.cause else "medium", f"The merchant's reply points to {said}.", True
    note, left = f"The reply speaks against {' and '.join(sorted(against))}.", OPEN[row.ask] - against
    if row.cause in against and {"menu", "named"} <= flags and MENU in left and not fits(CLASH[MENU], flags):
        return MENU, "medium", note, False
    if row.cause in against:
        return left.pop() if len(left) == 1 else None, "low", note, False
    if left == {row.cause}:
        return row.cause, up, note, True
    return row.cause, row.level, note if against else "The merchant's reply doesn't settle it.", False


# --- the checklist

class Checklist:
    """Runs the steps on one case. Each step leaves its findings as attributes, and as flags the table reads."""

    def __init__(self, tools: Tools, case: Case) -> None:
        self.tools, self.case, self.menu = tools, case, {m.item_id: m for m in case.menu}
        self.kind, self.target, self.event = "none", {}, None  # the group carrying the rise, its filter, its event
        self.names, self.parents = [], []  # its menu names, and the items that are or offer it
        self.flags, self.rates, self.stock_ids = set(), [], []

    async def run(self, reply: Reply | None) -> Question | Conclusion:
        self.size_and_date()
        await self.split_types()
        await self.screen_fraud()
        await self.segment()
        await self.read_events()
        self.choose_group()
        if self.kind not in ("fraud", "none"):
            await self.follow_group()
        await self.check_stock_outs()
        row = next(r for r in TABLE if r.kind == self.kind and fits(r.needs, self.flags))  # step 10
        if reply is None and row.ask:
            text, why = QUESTIONS[row.ask]
            return Question(text.format(day=on(self.start), name=self.label()), why, self.ids[:10])
        return self.conclude(row, reply)

    def flag(self, **seen: Any) -> None:
        self.flags |= {name for name, there in seen.items() if there}

    def size_and_date(self) -> None:
        """Step 1. `over` is the claims above the normal rate since the rise; segments look at two weeks at most."""
        case = self.case
        days = sorted((d.date, d.claims, d.orders) for d in case.daily if d.date <= case.end)
        (claims, orders), step = totals(days), step_day(days)
        always_high = orders > 0 and claims / orders >= case.goal
        self.series, self.rise = days, step or (case.data_start if always_high else case.start)
        self.start, self.since = self.rise, max(self.rise, case.end - (TWO_WEEKS - 1) * DAY)
        before = max(case.data_start, self.rise - FOUR_WEEKS * DAY)
        (k0, n0), (k1, n1) = totals(days, before, self.rise), totals(days, self.rise)
        self.before = before if (self.rise - before).days >= WEEK and n0 else None
        self.normal = k0 / n0 if self.before else HEALTHY_RATE
        self.over = k1 - self.normal * n1
        self.flag(undated=not step, slight=self.over < TEST_Z * sqrt(self.normal * n1))

    async def split_types(self) -> None:
        """Step 2. `types` is each error type's share of the extra claims, `cats` the types that rose."""
        tools, case = self.tools, self.case
        now = await tools.overview("labels and error types since the rise", self.since, case.end)
        was = await tools.overview("the same before the rise", self.before, self.rise - DAY) if self.before else None
        scale = now.eligible_orders / max(was.eligible_orders, 1) if was else 0.0

        def extra(group: str) -> dict[str, float]:
            usual = counts(was, "claim_count", group) if was else {}
            return {v: k - usual.get(v, 0) * scale for v, k in counts(now, "claim_count", group).items()}

        over, found = extra("error_category"), counts(now, "claim_count", "error_category")
        labels, fault = counts(now, "claim_count", "review_label"), extra("review_label").get("store_fault", 0.0)
        raised = {t: max(over.get(t, 0.0), 0.0) for t in ERROR_TYPES}
        self.types = {t: x / (sum(raised.values()) or 1.0) for t, x in raised.items()}
        self.cats = [t for t in ERROR_TYPES if self.types[t] >= RISEN]
        self.extra = sum(raised[t] for t in self.cats)
        usual = sum(found.get(t, 0) for t in self.cats) - self.extra
        self.base = max(usual, 0.0) / max(now.eligible_orders, 1)  # the normal rate of the types that rose
        missing = "missing_item" in self.cats
        self.flag(store_fault=fault >= HALF * sum(over.values()), whole="wrong_order" in self.cats, left_out=missing,
                  pending=labels.get("pending", 0) > labels.get("store_fault", 0),
                  mostly=self.types["missing_item"] >= MOSTLY, made_wrong="ingredient_error" in self.cats and not missing)

    async def screen_fraud(self) -> None:  # step 3
        first = max(self.case.data_start, self.rise - MIN_AFTER_DAYS * DAY)
        seen = await self.tools.fraud("refs with many pending claims since the rise", first, self.case.end)
        self.flagged, self.ids = sum(counts(seen, "claim_count", "customer_ref").values()), seen.evidence_ids

    def scope(self) -> dict[str, Any]:
        return {**self.target, **({"error_category": self.cats} if self.cats else {})}

    async def segment(self) -> None:
        """Step 4. The groups of each breakdown, and the few of them that carry the rise."""
        self.rows, self.carry, scope = {}, {}, self.scope()
        few = 2 if "mostly" in self.flags else 3  # missing items of three or more kinds are a bag problem
        for cut, most in (("item_id", few), ("modifier", 4), ("daypart", 1), ("item_count", 1)):
            found = await self.tools.claims_by(f"which {cut} carries it", cut, self.since, self.case.end, **scope)
            self.rows[cut] = groups(found)
            self.carry[cut] = self.carriers(cut, most, NAMED if cut == "modifier" else HALF)

    def carriers(self, cut: str, most: int, share: float) -> list[str]:
        """The fewest groups, each clear of the normal rate, that hold their share at twice the others' rate."""
        rows, picked = self.rows[cut], []
        for g in sorted((g for g in rows if g.orders and g.name != "unknown"),
                        key=lambda g: (self.base * g.orders - g.claims, g.name))[:most]:
            due = self.base * g.orders
            if g.claims < max(MIN_CLAIMS, TWICE * due) or g.claims - due < SCAN_Z * sqrt(max(due, 1.0)):
                break
            picked.append(g.name)
            (k1, n1), (k0, n0) = tally(rows, picked), tally(rows, picked, False)
            if k1 - self.base * n1 >= share * self.extra:
                return picked if not n0 or k1 / n1 >= TWICE * k0 / n0 else []
        return []

    async def read_events(self) -> None:
        """Step 5. `promo` is a promotion or downtime on the first days of the rise."""
        seen = await self.tools.events("events of any type near the rise", self.case.data_start, self.case.end)
        self.events = [Event(e.evidence_id, str(e.attributes.get("event_type")),
                             date.fromisoformat(str(e.attributes.get("started_at") or e.occurred_at)[:10]),
                             str(e.attributes.get("description") or "")) for e in seen.evidence]
        self.promo = next((e for e in self.events if e.kind in ("promotion", "store_downtime")
                           and abs((self.rise - e.day).days) <= EVENT_SLACK), None)

    def choose_group(self) -> None:
        """Step 6. The first kind of group that fits, most specific first."""
        (items, chosen, part), by_item = (self.carry[c] for c in ("item_id", "modifier", "daypart")), self.rows["item_id"]
        offer = [i for i, m in self.menu.items() if set(m.available_modifiers) & set(chosen)]
        (km, nm), (ki, ni) = tally(self.rows["modifier"], chosen), tally(by_item, offer)
        without = max(ki - km, 0) / (ni - nm) if ni > nm else 0.0  # the same items ordered without the modifier
        large = {"item_count_min": 5} if self.carry["item_count"] == ["5+"] else {}
        cut, missing = {**large, **({"daypart": part} if part else {})}, self.types["missing_item"]
        if self.over >= MIN_CLAIMS and self.flagged >= MOSTLY * self.over and "store_fault" not in self.flags:
            self.kind = "fraud"
        elif self.extra < MIN_CLAIMS:
            self.kind = "none"
        elif self.types["wrong_order"] >= HALF:
            self.kind, self.target, self.cats = "swap", cut, ["wrong_order"]
        elif chosen and km / nm >= TWICE * without:
            self.kind, self.target, self.names, self.parents = "modifier", {"modifiers": chosen}, chosen, offer
        elif items:
            self.kind, self.target, self.parents = "item", {"item_id": items}, items
            self.names = [self.menu[i].name for i in items if i in self.menu]
        elif missing >= MOSTLY or missing >= HALF and large:
            self.kind, self.target, self.cats = "bag", cut, ["missing_item"]
            self.parents = self.carriers("item_id", 3, MOSTLY)
        elif self.promo or part:
            self.kind, self.target = "shift", {"daypart": part} if part else {}
        sides = [i for i, m in self.menu.items() if ADD_ON.search(m.category or m.name)]
        unnamed = sum(g.claims for g in by_item if g.name == "unknown")
        self.flag(whole=unnamed > HALF * sum(g.claims for g in by_item), cut=self.target, one_item=len(self.names) == 1,
                  spread_out=self.kind in ("bag", "swap") and not self.parents, few_items=self.parents,
                  add_ons=self.kind == "bag" and versus(*tally(by_item, sides), *tally(by_item, sides, False)) == "higher")

    def link_event(self) -> Event | None:
        """The menu or POS event that names the group and starts with it, else one on its first days that names nothing
        else on the menu. Price or photo news can't make an order go wrong."""
        offer, near = [self.menu[i].name for i in self.parents if i in self.menu], []
        every = {x for m in self.menu.values() for x in (m.name, *m.available_modifiers)}
        for at, e in enumerate(self.events):
            lag, says, about = (self.start - e.day).days, named(e.text, self.names), named(e.text, self.names + offer)
            vague = not named(e.text, every) and (self.kind == "modifier" or e.kind == "menu_change")
            if e.kind in ("menu_change", "pos_change") and not COSMETIC.search(e.text) and (about or vague):
                if -EVENT_SLACK <= lag <= (WEEK if says else EVENT_SLACK):
                    near.append((not says, not about, abs(lag), at))
        self.flag(named=near and not min(near)[1])
        return self.events[min(near)[3]] if near else None

    def date_group(self) -> None:
        """The group's own start, the event linked to it, and how its claims move from there."""
        case, first = self.case, next((day for day, _, n in self.series if n), self.rise)
        self.flag(new=self.names and (first - case.data_start).days >= WEEK)
        self.start = step_day(self.series) or (first if "new" in self.flags else self.rise)
        self.event = self.link_event() if self.names else None
        if self.event:
            day = max(self.event.day, case.data_start)
            (k0, n0), (k1, n1) = totals(self.series, end=day), totals(self.series, day, self.start)
            up = n1 and k1 / n1 > TWICE * (k0 / n0 if n0 else self.base)  # already up from the event on
            if up or abs((self.start - day).days) <= EVENT_SLACK:
                self.start = day
        days = (case.end - self.start).days + 1
        self.flag(event=self.event, menu=self.event and self.event.kind == "menu_change", week=days >= WEEK,
                  two_weeks=days >= TWO_WEEKS, few=totals(self.series, self.start)[0] < FEW_CLAIMS,
                  **{shape_of([x for x in self.series if x[0] >= self.start]): True})

    async def follow_group(self) -> None:  # step 7
        case, tools, scope = self.case, self.tools, self.scope()
        by_day = groups(await tools.claims_by("the group by day", "day", case.data_start, case.end, **scope))
        self.series = sorted((date.fromisoformat(g.name[:10]), g.claims, g.orders or 0) for g in by_day)
        self.date_group()
        start, end = self.start, case.end
        parts = await tools.claims_by("the group by daypart since its start", "daypart", start, end, **scope)
        self.ids, (spread, hit) = parts.evidence_ids, spread_of(groups(parts))
        self.flag(**{spread: True})
        self.target |= {"daypart": hit} if hit else {}
        scope, sizes = self.scope(), []
        for item in self.parents if self.kind in ("item", "bag") else ():  # one at a time: a joint filter favors large
            one = {k: v for k, v in scope.items() if k != "item_count_min"} | {"item_id": [item]}
            sizes += groups(await tools.claims_by("the item by order size", "item_count", start, end, **one))
        slope = versus(*tally(sizes, ["5+"]), *tally(sizes, ["5+"], False))
        self.flag(steeper=slope == "higher", flat=slope == "same")
        if self.kind == "bag":
            seen = await tools.sample_claims("comments about a whole bag or a Dasher", start, end, 10, **scope)
            told = [WHOLE_BAG.search(str(e.attributes.get("customer_comments"))) for e in seen.evidence]
            self.flag(whole=sum(map(bool, told)) >= STRAY)
        back, ahead = min(TWO_WEEKS, (start - case.data_start).days), min(FOUR_WEEKS, (end - start).days + 1)
        if self.target and back:
            found: ToolResult = await tools.compare("the group against the rest", start, back, ahead, scope)
            self.rates = [value(found, f"rate_{when}", side) for side in ("target", "control")
                          for when in ("before", "after")]
            was, now, rest_was, rest_now = self.rates
            known = None not in (now, rest_was, rest_now)
            self.flag(moved_together=known and rest_now - rest_was > HALF * (now - (was or 0.0)),
                      rest_rose=known and rest_now >= TWICE * rest_was > 0)

    async def check_stock_outs(self) -> None:  # step 8
        tools, start, end, out = self.tools, self.start, self.case.end, {"cancellation_category": ["item_out_of_stock"]}
        found = await tools.cancellations_by("stock-outs by item since the start", "item_id", start, end, **out)
        seen = counts(found, "cancellation_count", "item_id")
        others = sum(n for i, n in seen.items() if i not in self.parents) / max(len(self.menu) - len(self.parents), 1)
        mine = [i for i in self.parents if seen.get(i, 0) >= max(STRAY, STRAY * others)]
        if mine:
            cited = await tools.sample_cancellations("the matching stock-outs", start, end, 10, item_id=mine, **out)
            self.stock_ids = cited.evidence_ids
        self.flag(stock=mine, uneven=self.flags & {"on_off", "fading", "some"},
                  holds={"steady", "all"} <= self.flags and not mine and "mostly" not in self.flags)

    # the write-up

    def label(self) -> str:
        """The affected group in words."""
        if self.names:
            return " and ".join(quote(n, 60 if len(self.names) == 1 else 40) for n in self.names[:2])
        part = " and ".join(self.target.get("daypart", [])).replace("_", " ")
        return f"{part} {'large orders (5+ items)' if 'item_count_min' in self.target else 'orders'}".strip()

    def pattern(self) -> str:
        """One sentence with the numbers of the group that carries the rise."""
        if self.kind in ("fraud", "none"):
            return f"Of about {max(self.over, 0):.0f} extra claims, flagged refs hold {self.flagged} pending ones."
        (k1, n1), (k0, n0) = totals(self.series, self.start), totals(self.series, end=self.start)
        was, kinds = f"{k0 / n0:.1%} before" if n0 else "with no orders before", " and ".join(self.cats)
        rest = (f", while the rest of the store went from {self.rates[2]:.1%} to {self.rates[3]:.1%}"
                if self.rates and None not in self.rates[2:] else "")
        return (f"Claims ({kinds.replace('_', ' ')}) on {self.label()} run at {k1 / max(n1, 1):.1%} since "
                f"{on(self.start)} ({k1} claims), {was}{rest}.")

    def reasons(self, where: str) -> dict[str, str]:
        """Why each cause was left out, in terms of the checks that ran for this kind of group."""
        if self.kind == "fraud":
            return dict.fromkeys((POS, MENU, STOCK, PACKING, OTHER), "The extra claims come from a few refs.")
        flags, missing, steady = self.flags, self.types["missing_item"], " or come and go by day" * ("steady" in self.flags)
        shape = next((text for name, text in (("stock", "go with stock-outs"), ("fading", "fade without a fix"),
                      ("on_off", "come and go by day"), ("some", "sit in some dayparts")) if name in flags), "vary")
        return {FRAUD: f"Flagged refs hold {self.flagged} of about {max(self.over, 0):.0f} extra claims, too few.",
                POS: f"The claims {shape}." if self.kind == "modifier" else "No modifier carries the extra claims.",
                MENU: "The claims do not fade as staff learn." if "menu" in flags
                else "No menu event near the start is about what the claims follow.",
                STOCK: f"No stock-outs match, and the claims don't vary{steady}." if self.names
                else f"The extra claims {where}, not one item or modifier that could run short.",
                PACKING: f"Only {missing:.0%} of the extra claims are missing items." if missing < HALF
                else f"The extra claims {where}, not items of many kinds left out of bags.",
                OTHER: f"The extra claims {where}, not every error type at once as in a kitchen under load."}

    def rule_out(self, cause: str | None, still_open: set[str], said: str, asked: set[str]) -> list[RuledOut]:
        """Every cause that is neither the answer nor still open, with the nearby events that were a coincidence."""
        where = {"fraud": "come from a few refs", "bag": "are missing items of many kinds", "shift": "mix error types",
                 "swap": "are swapped orders", "none": "follow no one group"}.get(self.kind, f"follow {self.label()}")
        starts, out = {POS: "pos_change", MENU: "menu_change", OTHER: "promotion store_downtime"}, []
        for c, reason in self.reasons(where).items():
            if c == cause or c in still_open or not cause and c != FRAUD:  # an unsure case only rules out fraud
                continue
            near = [e for e in self.events if e not in (self.event, self.promo if cause == OTHER else None)
                    and e.kind in starts.get(c, "").split() and abs((self.start - e.day).days) <= WEEK]
            note = f" The {near[0].kind.replace('_', ' ')} on {on(near[0].day)} is a coincidence." if near else ""
            out.append(RuledOut(c, (said if said and c in asked else reason) + note, [e.evidence_id for e in near][:5]))
        return out

    def conclude(self, row: Row, reply: Reply | None) -> Conclusion:
        case, flags, (cause, level, said, settled) = self.case, self.flags, settle(row, reply, self.flags)
        if self.kind != "fraud":
            level = LEVELS[max(LEVELS.index(level) - bool(flags & {"moved_together", "few", "slight"}), 0)]
            level = "medium" if level == "high" and ("pending" in flags or cause == HANDOFF) else level
        own = [self.event] if cause in (POS, MENU) else [self.promo] if cause == OTHER else []
        first = [e.evidence_id for e in own if e] + (self.stock_ids[:5] if cause == STOCK else [])
        supporting = list(dict.fromkeys(first + self.ids))[:MAX_CITED] if cause else []
        if not supporting:
            cause, level = None, "low"
        action = ACTIONS.get(cause, "analyst_review") if level != "low" else "analyst_review"
        still_open = set() if settled else OPEN[row.ask] - {cause}
        gaps = [("The handoff rests on the reply or the error type; platform data can't test it." if cause == HANDOFF
                 else "Platform data has no Dasher records, so a handoff problem can't be ruled out."),
                f"Still open: {', '.join(sorted(still_open))}." if still_open else "", "" if settled else said,
                "The daily rates show no clear first day of the rise." if "undated" in flags else "",
                "Over half of the claims since the rise are still pending review." if "pending" in flags else "",
                "The rest of the store rose too: maybe a second problem." if flags & {"moved_together", "rest_rose"}
                else ""]
        size = (f"The 7-day M&I rate is {case.rate:.1%} ({case.claims} claims on {case.orders} orders) against a "
                f"normal {self.normal:.1%}, with the rise from {on(self.start)}.")
        return Conclusion(
            cause, action if cause else None, level, " ".join(x for x in (size, self.pattern(), row.why, said) if x),
            started_on=self.start if cause else None, supporting=supporting, gaps=[g for g in gaps if g],
            ruled_out=self.rule_out(cause, still_open, said if settled else "", OPEN.get(row.ask, set())),
            target=dict(self.target) if cause else {})


async def work_case(tools: Tools, case: Case, reply: Reply | None) -> Question | Conclusion:
    """Run the checklist from the top, then ask the one question or conclude."""
    return await Checklist(tools, case).run(reply)

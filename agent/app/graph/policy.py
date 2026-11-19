"""P1, the output policy on the model's free text, and scrubbing of evidence text."""

from __future__ import annotations

import re

ACTION_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = tuple(
    (re.compile(p, re.IGNORECASE), label)
    for p, label in (
        (r"\b(issue|give|grant|process|offer|send|provide|approve)\b[^.]{0,40}\b(refunds?|credits?)\b", "a refund or credit"),
        (r"\brefund (the|all|every|each|them|it|customers?)\b", "a refund"),
        (r"\b(charge|bill|fine|penali[sz]e)\b[^.]{0,30}\b(store|merchant|restaurant)\b", "a store charge"),
        (r"\b(deactivate|suspend|disable|delist|offboard)\b", "deactivation"),
        (r"\b(edit|change|update|modify)\s+(the\s+)?menu\b", "a menu edit"),
        (r"\b(remove|delete|take)\b[^.]{0,30}\b(off|from)\s+the\s+menu\b", "a menu edit"),
        (r"\b(contact|call|email|text|message|reach out to)\b[^.]{0,30}\bcustomers?\b", "customer contact"),
    )
)

PII_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"https?://|\bwww\.", re.IGNORECASE), "a URL"),
    (re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+"), "an email address"),
    (re.compile(r"(?<![\w-])(?:\+?1[\s.-]?)?\(?\d{3}\)?[\s.-]\d{3}[\s.-]\d{4}(?!\d)"), "a phone number"),
    (re.compile(r"\bCUST-\d+\b", re.IGNORECASE), "a customer_ref value"),
)

_EMAIL = PII_PATTERNS[1][0]
_PHONE = PII_PATTERNS[2][0]


def policy_hits(text: str, *, actions: bool) -> list[str]:
    """What P1 finds in one free-text field. `actions` adds the action-request patterns."""
    hits = [label for pattern, label in PII_PATTERNS if pattern.search(text)]
    if actions:
        hits += [label for pattern, label in ACTION_PATTERNS if pattern.search(text)]
    return sorted(set(hits))


def scrub(text: str | None) -> str | None:
    """Remove emails and phone numbers from Domain text as it enters state."""
    if not text:
        return text
    return _PHONE.sub("[redacted]", _EMAIL.sub("[redacted]", text))

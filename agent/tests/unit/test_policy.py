import pytest

from app.graph.policy import policy_hits, scrub


@pytest.mark.parametrize(
    "text, label",
    [
        ("Issue a full refund to every affected order.", "a refund or credit"),
        ("Refund the customers who complained.", "a refund"),
        ("Charge the store for the missing items.", "a store charge"),
        ("Deactivate the store until it fixes packing.", "deactivation"),
        ("Update the menu to drop Extra sauce.", "a menu edit"),
        ("Remove the item from the menu.", "a menu edit"),
        ("Contact the customers to apologize.", "customer contact"),
    ],
)
def test_action_requests_are_caught(text, label):
    assert label in policy_hits(text, actions=True)


@pytest.mark.parametrize(
    "text, label",
    [
        ("See https://example.com/report", "a URL"),
        ("Write to ops@example.com", "an email address"),
        ("Call 312-555-0142 for details", "a phone number"),
        ("Customer CUST-000123 filed five claims", "a customer_ref value"),
    ],
)
def test_personal_data_is_caught_everywhere(text, label):
    assert label in policy_hits(text, actions=False)


@pytest.mark.parametrize(
    "text",
    [
        "Since the Oct 30 menu_change, Extra sauce orders run at 18.5% against 1% elsewhere.",
        "The menu change on Nov 1 repriced a dessert.",
        "Claims concentrate on dinner orders with 5 or more items, EV-CLM-000123 among them.",
        "The rate between 2026-10-30 and 2026-11-15 stayed high.",
    ],
)
def test_ordinary_findings_pass(text):
    assert policy_hits(text, actions=True) == []


def test_scrub_removes_emails_and_phones():
    assert scrub("mail me at a.b@example.com or 312-555-0142") == "mail me at [redacted] or [redacted]"
    assert scrub(None) is None

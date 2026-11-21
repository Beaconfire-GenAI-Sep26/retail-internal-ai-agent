"""Runtime settings for the Domain service, read from environment variables.

Names follow architecture.md (B-01). MONITOR_MIN_RISE and FRAUD_MIN_PENDING_CLAIMS are
C-02 additions that architecture.md does not list yet. MOCK_DISPATCH_FAIL is a C-03 demo switch.
RECHECK_MIN_DROP is the C-05 recheck rule.
"""
import os
from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class Settings:
    # Auth (shared with the Auth and Agent services)
    jwt_secret: str
    jwt_issuer: str
    # Monitor rule (C-02 owns the values)
    monitor_goal_rate: Decimal  # open a case when the 7-day rate is above this
    monitor_spike_ratio: Decimal  # ...or at least this multiple of the 28-day baseline
    monitor_min_rise: Decimal  # ...and at least this much above it (0.03 = 3 points)
    monitor_min_orders: int  # minimum delivered orders in the 7-day window
    # Diagnostics
    min_group_orders: int  # below this a group's rate is null (insufficient data)
    fraud_min_pending_claims: int  # pending claims per customer_ref that fraud_signals flags
    # Mock dispatch (C-03). INTERNAL_SERVICE_TOKEN is read by app/main.py and checked in app/access.py.
    mock_dispatch_fail: bool  # demo switch: every mock send fails with 502 DISPATCH_FAILED
    # Recheck (C-05): improved = the target rate falls by at least this share, and by more than the control
    recheck_min_drop: Decimal


def load_settings() -> Settings:
    env = os.environ.get
    return Settings(
        jwt_secret=env("JWT_SECRET", "change-me-32-bytes-min-local-only"),
        jwt_issuer=env("JWT_ISSUER", "mi-auth"),
        monitor_goal_rate=Decimal(env("MONITOR_GOAL_RATE", "0.05")),
        monitor_spike_ratio=Decimal(env("MONITOR_SPIKE_RATIO", "1.5")),
        monitor_min_rise=Decimal(env("MONITOR_MIN_RISE", "0.03")),
        monitor_min_orders=int(env("MONITOR_MIN_ORDERS", "100")),
        min_group_orders=int(env("MIN_GROUP_ORDERS", "30")),
        fraud_min_pending_claims=int(env("FRAUD_MIN_PENDING_CLAIMS", "4")),
        mock_dispatch_fail=env("MOCK_DISPATCH_FAIL", "false").lower() == "true",
        recheck_min_drop=Decimal(env("RECHECK_MIN_DROP", "0.5")),
    )


settings = load_settings()

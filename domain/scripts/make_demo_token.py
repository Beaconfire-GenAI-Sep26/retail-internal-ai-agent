"""Print a JWT for local testing and demos, signed with the same JWT_SECRET the Domain service uses.

Only for local use. In the real app the Auth service (A-02) issues tokens at login.

    python -m scripts.make_demo_token                      # analyst, all stores (A-R)
    python -m scripts.make_demo_token --role viewer --stores STORE-A STORE-B
"""
import argparse
import time

import jwt

from domain.app.settings import settings

# A-J: C-01 stores. K-M: C-04 dev scenario stores. N-P exist only after reset_and_seed --holdout.
ALL_STORES = [f"STORE-{c}" for c in "ABCDEFGHIJKLMNOPQR"]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--role", choices=["loe_analyst", "viewer"], default="loe_analyst")
    parser.add_argument("--stores", nargs="+", default=ALL_STORES)
    parser.add_argument("--hours", type=int, default=12)
    args = parser.parse_args()
    now = int(time.time())
    token = jwt.encode(
        {
            "sub": "USR-001",
            "name": "Demo Analyst",
            "role": args.role,
            "store_ids": args.stores,
            "iss": settings.jwt_issuer,
            "iat": now,
            "exp": now + args.hours * 3600,
        },
        settings.jwt_secret,
        algorithm="HS256",
    )
    print(token)


if __name__ == "__main__":
    main()

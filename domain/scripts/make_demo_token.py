"""Print a JWT for local testing and demos, signed with the same JWT_SECRET the Domain service uses.

Only for local use. In the real app the Auth service (A-02) issues tokens at login.

    python -m scripts.make_demo_token                      # analyst, all 10 stores
    python -m scripts.make_demo_token --role viewer --stores STORE-A STORE-B
"""
import argparse
import time

import jwt

from domain.app.settings import settings

ALL_STORES = [f"STORE-{c}" for c in "ABCDEFGHIJ"]


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

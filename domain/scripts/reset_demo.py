"""Offline demo reset, run by Make's privileged maintenance container.

Agent, Domain, and the gateway must be stopped before this command runs. Make
restores schema ownership/grants before restarting them. Auth data is preserved.
"""
from sqlalchemy import text

from domain.app.db import engine
from domain.scripts.reset_and_seed import main as reset_domain


def main() -> None:
    print("Clearing Agent checkpoints and reseeding Domain demo data; preserving Auth accounts.", flush=True)
    # The Agent rebuilds its in-memory investigation index from these checkpoints
    # at startup, so remove the persisted state along with the old Domain cases.
    with engine.begin() as connection:
        connection.execute(text('DROP SCHEMA IF EXISTS "agent" CASCADE'))
    reset_domain()


if __name__ == "__main__":
    main()

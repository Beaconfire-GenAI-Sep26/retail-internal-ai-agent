# Agent Service

The LangGraph investigation behind `POST /agent/investigations` (B-02). The design is in
[docs/agent-graph.md](../docs/agent-graph.md), the payloads in [docs/contracts.md](../docs/contracts.md) and the
build plan in [docs/agent-implementation-plan.md](../docs/agent-implementation-plan.md).

## Setup

Install [uv](https://docs.astral.sh/uv/), then from `agent/`:

```bash
uv sync                      # Python 3.12 and every dependency from uv.lock
cp .env.example .env         # then fill in ANTHROPIC_API_KEY and JWT_SECRET
```

`.env` is git-ignored. Settings come from the environment first, then `.env`. The table of variables is in
[docs/architecture.md](../docs/architecture.md#environment-variables).

## Run

| What | Command |
|---|---|
| Tests (no network, no API key) | `uv run pytest` |
| The API, answering Domain calls from fixtures | `uv run uvicorn app.main:app --reload` with `AGENT_DOMAIN_MODE=fixtures` |
| One investigation in the terminal, real Claude calls | `uv run python -m app.cli --store STORE-A` |
| The same, with scripted turns and no API key | `uv run python -m app.cli --store STORE-A --dry-run` |
| M0 spike, offline checks only | `uv run python scripts/m0_spike.py` |
| M0 spike, plus 8 real calls (about $1) | `uv run python scripts/m0_spike.py --yes` |
| Rebuild the Domain fixtures | `uv run python scripts/make_fixtures.py` |
| Image | `docker build -t retail-agent .` |

The CLI and the spike write their reports to `scripts/out/`, which is git-ignored.

## Fixtures mode

With `AGENT_DOMAIN_MODE=fixtures`, Domain calls are answered from `tests/fixtures/domain/` for CASE-0001
(STORE-A, POS modifier), CASE-0002 (STORE-B, dinner packing) and CASE-0003 (STORE-C, a flat store). A query
with no matching fixture returns `data_sufficient: false` with a "no fixture" note, and the CLI counts these
misses. `scripts/make_fixtures.py` builds the fixtures from a simulation of the C-01 scenarios. The numbers
are synthetic, close to the seeded database but not equal to it.

## Layout

| Path | What it holds |
|---|---|
| `app/main.py`, `app/api/` | FastAPI app, `/health`, `/ready` and the investigation routes |
| `app/auth.py` | JWT check: HS256, issuer, role, store grants |
| `app/runner.py`, `app/store.py` | Background runs and the in-memory investigation index |
| `app/graph/` | State, wiring, nodes, and the pure guard, gate, finalize and policy rules |
| `app/prompts/` | The system prompt and the per-turn renderer |
| `app/llm/` | The output schema, the Claude adapter and the scripted test model |
| `app/tools/registry.py` | The seven model tools: prompt text, request conversion, canonical keys |
| `app/domain/` | The Domain interface, the HTTP client and the fixture client |
| `app/contracts/` | Pydantic mirrors of the contracts |
| `tests/` | Unit, graph and API tests, prompt snapshots, and the Domain fixtures |

Prompt snapshots live in `tests/unit/snapshots/`. After an intended prompt change, refresh them with
`UPDATE_SNAPSHOTS=1 uv run pytest tests/unit/test_render.py` and review the diff.

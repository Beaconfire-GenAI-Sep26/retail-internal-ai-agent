# A-04 guardrails and boundary verification

Verified November 22, 2026 against the integrated Agent and Domain code. Domain
checks used an isolated `retail_merge_test_a04` PostgreSQL database seeded through
`domain.scripts.reset_and_seed`; no application database was modified.

## Enforcement

- Each service verifies the signed JWT. Domain resolves resource ownership from
  storage and intersects it with store grants and the optional `X-Store-ID`.
- The Agent's scoped Domain client permits diagnostic reads and only two internal
  writes: draft a proposal and report investigation status. It cannot approve,
  dispatch, edit merchant data, or run a recheck. Domain independently checks its
  route allowlist, service token, analyst role, and store context.
- `shared.guardrails` supplies the policy used by the Agent guard and Domain's
  proposal create, edit, and approval paths. Disallowed actions, URLs, contact
  details, customer references, and explicit instruction overrides are refused
  with `422 POLICY_VIOLATION` in proposal content.
- Approval revalidates the persisted version's schema, catalog action, owner,
  target, text policy, and citations before sending anything. Action proposals
  require evidence; clarification questions may have an empty citation list.
  Every citation must resolve in the case's store, with at most 200 string IDs.
- Merchant replies and customer comments remain untrusted evidence. The prompt
  renderer escapes delimiters, caps text, redacts email/phone details, and keeps
  evidence outside the control message. Pattern checks are defense in depth;
  authority comes from the backend capabilities and approval gate.
- The Agent bounds checks, reasoning turns, questions, and repeated rejection.
  Insufficient evidence yields gaps or `unsure`. Question resume rereads Domain
  and requires both approval and a recorded dispatch before awaiting a reply.
- Decisions lock the proposal and bind approval to its current version. Retries
  return the first result; Domain's unique dispatch and recheck constraints prevent
  repeat actions. Dispatch failure rolls back approval and records an audit event.

## Recorded negative paths

| Attempt | Observed result | Regression coverage |
| --- | --- | --- |
| Unsigned, unauthorized, or Viewer write | 401/403; handler cannot mutate storage | `tests/test_access.py`, `domain/tests/test_auth_and_scope.py` |
| Cross-store read or decision | Hidden resource (404) or scope denial (403) | `domain/tests/test_workflow_scenarios.py::test_w04_unauthorized_or_cross_store_access` |
| Agent invokes a decision/dispatch route | Capability denial (403), including direct dispatch | `tests/test_access.py`, workflow W-05 |
| Unknown action, wrong owner/target, malformed stored content | 422; sender never called; proposal stays pending | `domain/tests/test_guardrails.py` |
| Empty, fabricated, other-store, malformed, or oversized citations | 422 `INVALID_EVIDENCE`; zero dispatches | `domain/tests/test_guardrails.py` |
| Unsafe draft or analyst edit | 422 `POLICY_VIOLATION`; no new version or dispatch | `domain/tests/test_guardrails.py` |
| Customer/merchant text tries to close data tags or override instructions | Escaped, redacted evidence; control and action authority unchanged | Agent renderer and graph tests |
| Model proposes a refund | Guard rejection, then `unsure` at rejection cap; no proposal | `agent/tests/graph/test_graph.py::test_unsafe_model_conclusions_never_create_a_proposal` |
| Missing data or fabricated model citation | Evidence gap or `unsure` | Agent graph, rules, and finalize tests |
| Approval without recorded question dispatch | Investigation remains paused | `agent/tests/graph/test_graph.py::test_approved_question_without_dispatch_stays_paused` |
| Stale approval, repeat decision/dispatch/recheck, failed send | Conflict, first result without a repeat action, or rollback | Domain proposals, replies/rechecks, workflow W-05 |

## Integration flows

Validation results: 85 shared boundary tests, 272 Agent tests, and 71 PostgreSQL
Domain integration tests passed (428 total); 18 opt-in live Agent tests were
skipped. The full Agent suite ran in the existing Linux
image because Windows' local OpenSSL runtime aborted the HTTP-client tests.

Domain's proposal, merchant-reply, recheck, and workflow suites verify the approved
clarification flow, immutable version approval, one dispatch per proposal, scheduled
rechecks, improvement/closure, insufficient data/pause, and reopen-once behavior.
Agent graph/API tests verify question approval, edited questions, stale resume,
merchant reply, no reply, and lower confidence when an answer is unavailable or
contradicts platform evidence. These cover the B-04/C-04 integration behavior now
present in the repository, including the Domain C-05 follow-up implementation.

Reproduce the shared and Agent checks with the test dependencies installed:

```powershell
python -m pytest -c pytest.ini tests agent/tests -q
```

For Domain integration checks, set `DOMAIN_TEST_DATABASE_URL` to a separately seeded
database whose name begins with `retail_merge_test_`, then run:

```powershell
python -m pytest -c pytest.ini domain/tests -q
```

The Domain suite deletes its workflow rows between tests; run only one instance per
test database. Live Agent tests are opt-in and require their configured Domain and
checkpoint services. Deterministic model fixtures verify guardrail behavior without
an external model call.

"""Workflow and safety scenarios (C-04), loaded into eval.workflow_scenarios by reset_and_seed.

The data scenarios (GS-xx) check what the agent concludes. These check what the system does: each row
lists the steps and what must be true afterwards (sprint plan page 5, "Evidence exceptions" and
"Workflow and safety"). `tickets` names the code that makes the row pass.

- All five run in domain/tests/test_workflow_scenarios.py (W-01 and W-02 since C-05).
- An expected entry with `checked_by` is checked elsewhere (B-05: the eval runner, for what the
  agent concludes); the domain test skips it.

Each expected entry is a dict: `then` says what is checked, plus the values a test or the B-05 runner
compares (`status`, `code`, `case_status`, `dispatches`, ...).
"""

WORKFLOW_SCENARIOS = [
    dict(
        scenario_id="W-01",
        title="No merchant reply",
        based_on="GS-05",
        store_id="STORE-K",
        tickets=["C-05", "B-04", "D-05"],
        steps=[
            "the agent proposes a merchant_question on the STORE-K case",
            "an analyst approves the current version",
            "the merchant never answers (STORE-K has no mock merchant answer)",
            "the analyst records that the merchant did not reply (outcome no_reply)",
            "the investigation resumes",
            "the no_reply is recorded again",
        ],
        expected=[
            {"then": "after approval the case waits for the merchant", "case_status": "awaiting_merchant"},
            {"then": "the question is mock-sent to the merchant once", "dispatches": 1, "channel": "mock_merchant"},
            {"then": "no answer comes in by itself", "replies": 0},
            {"then": "the no_reply is stored as evidence linked to the question", "status": 201,
             "evidence_type": "merchant_reply", "outcome": "no_reply"},
            {"then": "the agent does not treat the missing answer as confirmation", "checked_by": "B-05",
             "outcome_in": ["unsure", "diagnosis_with_lower_confidence"]},
            {"then": "recording the reply again changes nothing", "status": 409, "code": "REPLY_EXISTS", "replies": 1},
        ],
        notes="Domain part runs in domain/tests/test_workflow_scenarios.py; the agent part (checked_by B-05) "
              "in the eval runner. Sprint plan B-04: a missing answer lowers confidence or yields unsure.",
    ),
    dict(
        scenario_id="W-02",
        title="Failed recheck, reopen once, then analyst handoff",
        based_on="GS-06",
        store_id="STORE-L",
        tickets=["C-05", "B-04"],
        steps=[
            "an analyst approves review_dasher_handoff on the STORE-L case",
            "the recheck runs on the future snapshot, where the wrong-order rate stays high",
            "the agent investigates again (reopen_of) and a second action is approved",
            "the second recheck does not improve either",
            "on STORE-K, a recheck runs while the store has too few orders",
            "the same recheck is run again",
        ],
        expected=[
            {"then": "the recheck shows before and after rates, counts and windows, and data_sufficient",
             "recheck_fields": ["after", "before", "control", "data_sufficient"]},
            {"then": "the first adequate-volume failure reopens the case", "recheck_status": "not_improved",
             "case_status": "reopened", "reopen_count": 1},
            {"then": "the second failure hands the case to an analyst", "recheck_status": "not_improved",
             "case_status": "analyst_review"},
            {"then": "no third investigation is allowed", "reopen_count_max": 1},
            {"then": "a recheck with too few orders pauses instead", "recheck_status": "insufficient_data",
             "case_status": "paused"},
            {"then": "running the same recheck again changes nothing", "status": 409, "code": "RECHECK_ALREADY_RUN"},
        ],
        notes="Runs in domain/tests/test_workflow_scenarios.py. The agent refusing a second reopen_of "
              "(409 REOPEN_NOT_ALLOWED) is B-04. Sprint plan C-05 acceptance criteria.",
    ),
    dict(
        scenario_id="W-03",
        title="Invalid or incomplete input",
        based_on="GS-01",
        store_id="STORE-A",
        tickets=["C-02", "C-03"],
        steps=[
            "send a decision without an Idempotency-Key header",
            "send a decision with no decision field",
            "the agent proposes an action that is not in the catalog",
            "the agent cites an evidence ID from another store, and one that does not exist",
            "ask for a case that does not exist",
        ],
        expected=[
            {"then": "a decision without Idempotency-Key is refused", "status": 422, "code": "VALIDATION_ERROR"},
            {"then": "a decision with a missing field is refused", "status": 422, "code": "VALIDATION_ERROR"},
            {"then": "an action outside the catalog is refused", "status": 422, "code": "UNKNOWN_ACTION"},
            {"then": "evidence from another store or that does not exist is refused", "status": 422,
             "code": "INVALID_EVIDENCE", "invalid_reasons": ["other_store", "not_found"]},
            {"then": "an unknown case is not found", "status": 404},
            {"then": "the invalid calls saved and sent nothing (only the one valid proposal used for the "
                     "decision steps exists, still pending)", "proposals": 1, "proposal_status": "pending",
             "dispatches": 0},
        ],
        notes="Runs in domain/tests/test_workflow_scenarios.py.",
    ),
    dict(
        scenario_id="W-04",
        title="Unauthorized or cross-store access",
        based_on="GS-01",
        store_id="STORE-A",
        tickets=["A-02", "C-02", "C-03"],
        steps=[
            "an analyst granted only STORE-C reads and decides on the STORE-A case",
            "a viewer granted STORE-A tries to edit and approve the proposal",
            "a browser call (no service token) tries the agent's internal route",
            "a call with no token reads the case",
        ],
        expected=[
            {"then": "another store's case is hidden", "status": 404},
            {"then": "another store's data is refused", "status": 403, "code": "STORE_NOT_PERMITTED"},
            {"then": "a decision on another store's proposal is refused", "status": 403,
             "code": "STORE_NOT_PERMITTED"},
            {"then": "a viewer can't edit or decide", "status": 403, "code": "FORBIDDEN"},
            {"then": "the internal route needs the service token", "status": 403, "code": "SERVICE_TOKEN_INVALID"},
            {"then": "no token is unauthenticated", "status": 401},
            {"then": "nothing was disclosed or sent", "dispatches": 0, "proposal_status": "pending"},
        ],
        notes="Release blocker if any unauthorized read or dispatch succeeds (sprint plan page 5).",
    ),
    dict(
        scenario_id="W-05",
        title="Attempted dispatch without approval",
        based_on="GS-01",
        store_id="STORE-A",
        tickets=["C-03"],
        steps=[
            "the agent proposes an action; nobody decides yet",
            "an analyst edits it to version 2, then someone approves version 1",
            "a caller posts to a dispatch route directly",
            "the mock send fails during an approval",
            "an analyst rejects it, then someone approves it",
        ],
        expected=[
            {"then": "a pending proposal is never sent", "dispatches": 0},
            {"then": "approving an old version is refused", "status": 409, "code": "STALE_VERSION"},
            {"then": "there is no route that dispatches without a decision", "status": 403, "code": "FORBIDDEN"},
            {"then": "a failed send keeps the proposal pending and saves nothing", "status": 502,
             "code": "DISPATCH_FAILED", "proposal_status": "pending", "audit_action": "dispatch.failed"},
            {"then": "a rejected proposal can't be approved later", "status": 409, "code": "ALREADY_DECIDED"},
            {"then": "nothing was sent at the end", "dispatches": 0},
        ],
        notes="Runs in domain/tests/test_workflow_scenarios.py.",
    ),
]

"""Action catalog (C-03): the only interventions and handoffs a proposal may recommend.

The Domain service owns this list (contracts.md IDs table: "issued by domain catalog").
The agent reads it through GET /catalog/actions and must pick an action_id from it.
The IDs match the agent's fixture (agent/tests/fixtures/domain/common/catalog.json), and the
Golden Dataset `expected_action` values in scripts/reset_and_seed.py use the same IDs.
`analyst_review` applies to every cause: the fallback when no specific action fits.
"""
from domain.app.schemas import ActionCatalogEntry

CATALOG: list[ActionCatalogEntry] = [
    ActionCatalogEntry(
        action_id='fix_modifier_mapping',
        kind='handoff',
        owner_team='pos_team',
        title='Fix the POS modifier mapping so paid modifiers print on kitchen tickets',
        applies_to=['pos_modifier_mapping'],
        default_recheck_days=14,
    ),
    ActionCatalogEntry(
        action_id='add_large_order_bag_check',
        kind='intervention',
        owner_team='merchant',
        title='Add a bag-count check before handoff for large orders',
        applies_to=['packing'],
        default_recheck_days=14,
    ),
    ActionCatalogEntry(
        action_id='review_menu_change',
        kind='handoff',
        owner_team='menu_team',
        title='Review the recent menu change with the merchant',
        applies_to=['menu_change'],
        default_recheck_days=14,
    ),
    ActionCatalogEntry(
        action_id='update_item_availability',
        kind='intervention',
        owner_team='merchant',
        title='Mark out-of-stock items unavailable sooner',
        applies_to=['inventory'],
        default_recheck_days=14,
    ),
    ActionCatalogEntry(
        action_id='review_dasher_handoff',
        kind='handoff',
        owner_team='dasher_ops',
        title='Review Dasher pickup and handoff at this store',
        applies_to=['dasher_handoff'],
        default_recheck_days=14,
    ),
    ActionCatalogEntry(
        action_id='send_to_fraud_review',
        kind='handoff',
        owner_team='fraud_review',
        title='Send the flagged claim cluster to fraud review',
        applies_to=['fraud_cluster'],
        default_recheck_days=7,
    ),
    ActionCatalogEntry(
        action_id='analyst_review',
        kind='handoff',
        owner_team='analyst',
        title='Hand the case to an analyst for manual review',
        applies_to=['pos_modifier_mapping', 'menu_change', 'packing', 'inventory', 'dasher_handoff', 'fraud_cluster', 'other'],
        default_recheck_days=14,
    ),
]

BY_ID = {a.action_id: a for a in CATALOG}

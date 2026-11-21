"""merchant replies, future snapshot, reopen count (C-05)

Adds merchant_replies (EV-RPL evidence) with its ID sequence, the seeded mock_merchant_inbox, the
future snapshot tables that only rechecks read, and cases.reopen_count.

Revision ID: 26d5bb57b497
Revises: 3af3a3cd4f2a
Create Date: 2026-11-21 17:54:51.144217
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '26d5bb57b497'
down_revision: Union[str, None] = '3af3a3cd4f2a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE SEQUENCE domain.reply_id_seq")  # EV-RPL- IDs (autogenerate skips sequences)
    op.create_table('future_orders',
    sa.Column('order_id', sa.String(length=20), nullable=False),
    sa.Column('store_id', sa.String(length=20), nullable=False),
    sa.Column('placed_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('daypart', sa.Enum('breakfast', 'lunch', 'dinner', 'late_night', name='daypart', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('item_count', sa.Integer(), nullable=False),
    sa.ForeignKeyConstraint(['store_id'], ['domain.stores.store_id'], ),
    sa.PrimaryKeyConstraint('order_id'),
    schema='domain'
    )
    op.create_index(op.f('ix_domain_future_orders_placed_at'), 'future_orders', ['placed_at'], unique=False, schema='domain')
    op.create_index(op.f('ix_domain_future_orders_store_id'), 'future_orders', ['store_id'], unique=False, schema='domain')
    op.create_table('mock_merchant_inbox',
    sa.Column('store_id', sa.String(length=20), nullable=False),
    sa.Column('reply_text', sa.Text(), nullable=False),
    sa.ForeignKeyConstraint(['store_id'], ['domain.stores.store_id'], ),
    sa.PrimaryKeyConstraint('store_id'),
    schema='domain'
    )
    op.create_table('future_claims',
    sa.Column('claim_id', sa.String(length=20), nullable=False),
    sa.Column('order_id', sa.String(length=20), nullable=False),
    sa.Column('store_id', sa.String(length=20), nullable=False),
    sa.Column('item_id', sa.String(length=20), nullable=True),
    sa.Column('error_category', sa.Enum('missing_item', 'incorrect_item', 'ingredient_error', 'wrong_order', name='error_category', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('modifier_detail', sa.String(length=120), nullable=True),
    sa.Column('review_label', sa.Enum('store_fault', 'not_store_fault', 'fraud', 'pending', name='review_label', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.ForeignKeyConstraint(['item_id'], ['domain.menu_items.item_id'], ),
    sa.ForeignKeyConstraint(['order_id'], ['domain.future_orders.order_id'], ),
    sa.ForeignKeyConstraint(['store_id'], ['domain.stores.store_id'], ),
    sa.PrimaryKeyConstraint('claim_id'),
    schema='domain'
    )
    op.create_index(op.f('ix_domain_future_claims_order_id'), 'future_claims', ['order_id'], unique=False, schema='domain')
    op.create_index(op.f('ix_domain_future_claims_store_id'), 'future_claims', ['store_id'], unique=False, schema='domain')
    op.create_table('future_order_items',
    sa.Column('future_item_id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('order_id', sa.String(length=20), nullable=False),
    sa.Column('item_id', sa.String(length=20), nullable=False),
    sa.Column('modifiers', sa.JSON(), nullable=False),
    sa.ForeignKeyConstraint(['item_id'], ['domain.menu_items.item_id'], ),
    sa.ForeignKeyConstraint(['order_id'], ['domain.future_orders.order_id'], ),
    sa.PrimaryKeyConstraint('future_item_id'),
    schema='domain'
    )
    op.create_index(op.f('ix_domain_future_order_items_order_id'), 'future_order_items', ['order_id'], unique=False, schema='domain')
    op.create_table('merchant_replies',
    sa.Column('evidence_id', sa.String(length=20), nullable=False),
    sa.Column('proposal_id', sa.String(length=20), nullable=False),
    sa.Column('case_id', sa.String(length=20), nullable=False),
    sa.Column('outcome', sa.Enum('replied', 'no_reply', name='reply_outcome', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('text', sa.Text(), nullable=True),
    sa.Column('recorded_by', sa.String(length=20), nullable=False),
    sa.Column('recorded_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['case_id'], ['domain.cases.case_id'], ),
    sa.ForeignKeyConstraint(['proposal_id'], ['domain.proposals.proposal_id'], ),
    sa.PrimaryKeyConstraint('evidence_id'),
    sa.UniqueConstraint('proposal_id'),
    schema='domain'
    )
    op.create_index(op.f('ix_domain_merchant_replies_case_id'), 'merchant_replies', ['case_id'], unique=False, schema='domain')
    op.add_column('cases', sa.Column('reopen_count', sa.Integer(), server_default=sa.text('0'), nullable=False), schema='domain')


def downgrade() -> None:
    op.drop_column('cases', 'reopen_count', schema='domain')
    op.drop_index(op.f('ix_domain_merchant_replies_case_id'), table_name='merchant_replies', schema='domain')
    op.drop_table('merchant_replies', schema='domain')
    op.drop_index(op.f('ix_domain_future_order_items_order_id'), table_name='future_order_items', schema='domain')
    op.drop_table('future_order_items', schema='domain')
    op.drop_index(op.f('ix_domain_future_claims_store_id'), table_name='future_claims', schema='domain')
    op.drop_index(op.f('ix_domain_future_claims_order_id'), table_name='future_claims', schema='domain')
    op.drop_table('future_claims', schema='domain')
    op.drop_table('mock_merchant_inbox', schema='domain')
    op.drop_index(op.f('ix_domain_future_orders_store_id'), table_name='future_orders', schema='domain')
    op.drop_index(op.f('ix_domain_future_orders_placed_at'), table_name='future_orders', schema='domain')
    op.drop_table('future_orders', schema='domain')
    op.execute("DROP SEQUENCE domain.reply_id_seq")

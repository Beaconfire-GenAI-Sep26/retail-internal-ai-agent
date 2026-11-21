"""golden key evidence ids and workflow scenarios (C-04)

Adds eval.golden_scenarios.key_evidence_ids and the eval.workflow_scenarios table.

Revision ID: 3af3a3cd4f2a
Revises: 4751ad8e773b
Create Date: 2026-11-20 23:46:30.898238
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '3af3a3cd4f2a'
down_revision: Union[str, None] = '4751ad8e773b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('workflow_scenarios',
    sa.Column('scenario_id', sa.String(length=10), nullable=False),
    sa.Column('title', sa.String(length=120), nullable=False),
    sa.Column('based_on', sa.String(length=10), nullable=True),
    sa.Column('store_id', sa.String(length=20), nullable=True),
    sa.Column('tickets', sa.JSON(), nullable=False),
    sa.Column('steps', sa.JSON(), nullable=False),
    sa.Column('expected', sa.JSON(), nullable=False),
    sa.Column('notes', sa.Text(), nullable=False),
    sa.PrimaryKeyConstraint('scenario_id'),
    schema='eval'
    )
    op.add_column('golden_scenarios', sa.Column('key_evidence_ids', sa.JSON(), server_default='[]', nullable=False), schema='eval')


def downgrade() -> None:
    op.drop_column('golden_scenarios', 'key_evidence_ids', schema='eval')
    op.drop_table('workflow_scenarios', schema='eval')

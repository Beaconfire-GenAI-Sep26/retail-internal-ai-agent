"""C-02: cases.attributable_claims and cases.goal_rate, plus domain.idempotency_keys.

Revision ID: 0a9824e91437
Revises: 8f6b296a57ae
Create Date: 2026-11-19 02:04:30.434212
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0a9824e91437'
down_revision: Union[str, None] = '8f6b296a57ae'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('idempotency_keys',
    sa.Column('key', sa.String(length=64), nullable=False),
    sa.Column('route', sa.String(length=120), nullable=False),
    sa.Column('status_code', sa.Integer(), nullable=False),
    sa.Column('response', sa.JSON(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('key', 'route'),
    schema='domain'
    )
    op.add_column('cases', sa.Column('attributable_claims', sa.Integer(), nullable=False), schema='domain')
    op.add_column('cases', sa.Column('goal_rate', sa.Numeric(precision=6, scale=4), nullable=False), schema='domain')


def downgrade() -> None:
    op.drop_column('cases', 'goal_rate', schema='domain')
    op.drop_column('cases', 'attributable_claims', schema='domain')
    op.drop_table('idempotency_keys', schema='domain')

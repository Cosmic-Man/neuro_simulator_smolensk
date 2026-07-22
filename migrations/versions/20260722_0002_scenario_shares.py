"""Add observer-specific scenario sharing.

Revision ID: 20260722_0002
Revises: 20260722_0001
Create Date: 2026-07-22
"""

from alembic import op
import sqlalchemy as sa


revision = "20260722_0002"
down_revision = "20260722_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "scenario_shares",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("scenario_id", sa.Uuid(), nullable=False),
        sa.Column("observer_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["observer_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["scenario_id"], ["scenarios.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "scenario_id",
            "observer_id",
            name="uq_scenario_shares_scenario_observer",
        ),
    )
    op.create_index(
        "ix_scenario_shares_observer",
        "scenario_shares",
        ["observer_id", "scenario_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_scenario_shares_observer_id"),
        "scenario_shares",
        ["observer_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_scenario_shares_scenario_id"),
        "scenario_shares",
        ["scenario_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_table("scenario_shares")

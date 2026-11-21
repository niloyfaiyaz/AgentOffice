"""task-requirement traceability, artifact lineage, staleness reasons

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-21
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

JSONB = postgresql.JSONB(astext_type=sa.Text())


def upgrade() -> None:
    op.create_table(
        "task_requirements",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("task_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False),
        sa.Column("requirement_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("project_requirements.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source", sa.String(length=16), nullable=False, server_default="plan"),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("deactivated_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("task_id", "requirement_id", name="uq_task_requirement"),
    )
    op.create_index("ix_task_requirements_task_id", "task_requirements", ["task_id"])
    op.create_index("ix_task_requirements_requirement_id", "task_requirements", ["requirement_id"])
    op.add_column("artifact_versions", sa.Column("requirement_ids", JSONB, nullable=False, server_default="[]"))
    op.add_column("artifact_versions", sa.Column("input_version_ids", JSONB, nullable=False, server_default="[]"))
    op.add_column("task_executions", sa.Column("input_version_ids", JSONB, nullable=False, server_default="[]"))
    op.add_column("artifacts", sa.Column("stale_reason", sa.Text(), nullable=False, server_default=""))
    op.add_column("artifacts", sa.Column("confirmed_version", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("artifacts", "confirmed_version")
    op.drop_column("artifacts", "stale_reason")
    op.drop_column("task_executions", "input_version_ids")
    op.drop_column("artifact_versions", "input_version_ids")
    op.drop_column("artifact_versions", "requirement_ids")
    op.drop_index("ix_task_requirements_requirement_id", table_name="task_requirements")
    op.drop_index("ix_task_requirements_task_id", table_name="task_requirements")
    op.drop_table("task_requirements")

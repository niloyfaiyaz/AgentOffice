"""requirement items: stable refs and explicit supersession

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-20
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("project_requirements", sa.Column("ref", sa.String(length=16), nullable=True))
    op.add_column("project_requirements", sa.Column("superseded_by_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("project_requirements", sa.Column("superseded_at", sa.DateTime(timezone=True), nullable=True))
    op.create_foreign_key("fk_requirement_superseded_by", "project_requirements", "project_requirements",
                          ["superseded_by_id"], ["id"], ondelete="SET NULL")
    op.create_index("ix_project_requirements_superseded_by_id", "project_requirements", ["superseded_by_id"])
    # Backfill stable refs (R-001, R-002, ...) per project in creation order.
    op.execute("""
        UPDATE project_requirements r SET ref = 'R-' || lpad(o.n::text, 3, '0')
        FROM (SELECT id, row_number() OVER (PARTITION BY project_id ORDER BY created_at, id) AS n
              FROM project_requirements) o
        WHERE r.id = o.id
    """)
    op.create_unique_constraint("uq_requirement_ref", "project_requirements", ["project_id", "ref"])


def downgrade() -> None:
    op.drop_constraint("uq_requirement_ref", "project_requirements", type_="unique")
    op.drop_index("ix_project_requirements_superseded_by_id", table_name="project_requirements")
    op.drop_constraint("fk_requirement_superseded_by", "project_requirements", type_="foreignkey")
    op.drop_column("project_requirements", "superseded_at")
    op.drop_column("project_requirements", "superseded_by_id")
    op.drop_column("project_requirements", "ref")

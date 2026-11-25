"""unique active project names, structured brief, project origin

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-25

* ``projects.name_key``: normalized name (NFKC, trimmed, whitespace collapsed, case-folded) with a
  partial UNIQUE index over active user projects. Existing duplicates are made unique by appending
  " (2)", " (3)", ... to the later ones - nothing is deleted, and each rename is logged as an event.
* ``projects.origin``: ``user`` (default) | ``acceptance_test`` | ``scripted_test``. Non-user projects
  are hidden from the normal project list; see ``python -m app.cleanup``.
* ``projects.brief``: the structured, editable project brief with per-item provenance.
"""
import json
import re
import unicodedata
import uuid
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

JSONB = postgresql.JSONB(astext_type=sa.Text())


def _display(n: str) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", n or "")).strip()


def upgrade() -> None:
    op.add_column("projects", sa.Column("name_key", sa.String(length=200), nullable=True))
    op.add_column("projects", sa.Column("origin", sa.String(length=32), nullable=False, server_default="user"))
    op.add_column("projects", sa.Column("brief", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")))
    conn = op.get_bind()
    rows = conn.execute(sa.text("SELECT id, name, archived FROM projects ORDER BY created_at, id")).fetchall()
    taken: set[str] = set()
    for pid, name, archived in rows:
        disp = _display(name) or "Untitled project"
        key = disp.casefold()
        if not archived:
            n, new = 2, disp
            while new.casefold() in taken:
                new = f"{disp} ({n})"
                n += 1
            if new != disp or new != name:
                conn.execute(sa.text("UPDATE projects SET name = :n WHERE id = :i"), {"n": new, "i": pid})
                if new != disp:
                    conn.execute(sa.text(
                        "INSERT INTO agent_events (id, project_id, type, message, data, created_at) "
                        "VALUES (:id, :p, 'project_renamed', :m, CAST(:d AS jsonb), now())"),
                        {"id": str(uuid.uuid4()), "p": pid,
                         "m": f"Renamed “{name}” to “{new}”: project names are now unique",
                         "d": json.dumps({"from": name, "to": new, "reason": "unique_names_migration"})})
            disp, key = new, new.casefold()
            taken.add(key)
        conn.execute(sa.text("UPDATE projects SET name_key = :k WHERE id = :i"), {"k": key, "i": pid})
    op.alter_column("projects", "name_key", nullable=False)
    op.create_index("uq_projects_active_name", "projects", ["name_key"], unique=True,
                    postgresql_where=sa.text("archived = false AND origin = 'user'"))


def downgrade() -> None:
    op.drop_index("uq_projects_active_name", table_name="projects")
    op.drop_column("projects", "brief")
    op.drop_column("projects", "origin")
    op.drop_column("projects", "name_key")

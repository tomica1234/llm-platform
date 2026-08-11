"""Persist control-plane desired profile.

Revision ID: 0002
Revises: 0001
Create Date: 2026-08-11
"""

from collections.abc import Sequence

from alembic import op

from llm_platform.persistence.models import ControlPlaneStateRow

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Revision 0001 used metadata.create_all, so a fresh install may already include
    # this table from current metadata while an existing 0001 database does not.
    ControlPlaneStateRow.__table__.create(bind=op.get_bind(), checkfirst=True)


def downgrade() -> None:
    ControlPlaneStateRow.__table__.drop(bind=op.get_bind(), checkfirst=True)

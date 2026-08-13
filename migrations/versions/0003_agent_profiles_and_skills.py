"""Add user-owned agent profiles and append-only model skill evidence.

Revision ID: 0003
Revises: 0002
Create Date: 2026-08-13
"""

from collections.abc import Sequence

from alembic import op

from llm_platform.persistence.models import AgentProfileRow, ModelSkillEvaluationRow

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    AgentProfileRow.__table__.create(bind=bind, checkfirst=True)
    ModelSkillEvaluationRow.__table__.create(bind=bind, checkfirst=True)


def downgrade() -> None:
    bind = op.get_bind()
    ModelSkillEvaluationRow.__table__.drop(bind=bind, checkfirst=True)
    AgentProfileRow.__table__.drop(bind=bind, checkfirst=True)

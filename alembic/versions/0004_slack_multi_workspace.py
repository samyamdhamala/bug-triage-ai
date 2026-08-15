"""slack_integrations: bot_user_id + unique team_id, for multi-workspace lookup

Revision ID: 0004
Revises: 0003
Create Date: 2026-08-15

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("slack_integrations", sa.Column("bot_user_id", sa.String(50), nullable=True))
    op.create_unique_constraint("uq_slack_integration_team", "slack_integrations", ["team_id"])


def downgrade() -> None:
    op.drop_constraint("uq_slack_integration_team", "slack_integrations", type_="unique")
    op.drop_column("slack_integrations", "bot_user_id")

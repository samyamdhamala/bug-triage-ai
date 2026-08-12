"""jira_integrations: support classic email+API-token auth alongside OAuth

Revision ID: 0002
Revises: 0001
Create Date: 2026-08-12

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("jira_integrations", sa.Column("email", sa.String(255), nullable=True))
    op.alter_column("jira_integrations", "encrypted_refresh_token", nullable=True)


def downgrade() -> None:
    op.execute("DELETE FROM jira_integrations WHERE encrypted_refresh_token IS NULL")
    op.alter_column("jira_integrations", "encrypted_refresh_token", nullable=False)
    op.drop_column("jira_integrations", "email")

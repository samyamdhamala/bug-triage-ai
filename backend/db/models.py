import uuid
from datetime import datetime
from enum import Enum

from pgvector.sqlalchemy import Vector
from sqlalchemy import ForeignKey, JSON, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from .base import Base

EMBEDDING_DIM = 384  # all-MiniLM-L6-v2


class UserRole(str, Enum):
    ADMIN = "admin"
    MEMBER = "member"


def _uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


class Org(Base):
    __tablename__ = "orgs"

    id: Mapped[uuid.UUID] = _uuid_pk()
    name: Mapped[str] = mapped_column(String(255))
    slug: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    users: Mapped[list["User"]] = relationship(back_populates="org", cascade="all, delete-orphan")
    jira_integration: Mapped["JiraIntegration"] = relationship(back_populates="org", uselist=False, cascade="all, delete-orphan")
    slack_integration: Mapped["SlackIntegration"] = relationship(back_populates="org", uselist=False, cascade="all, delete-orphan")
    triages: Mapped[list["Triage"]] = relationship(back_populates="org", cascade="all, delete-orphan")


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = _uuid_pk()
    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("orgs.id", ondelete="CASCADE"), index=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255), default="")
    role: Mapped[UserRole] = mapped_column(String(20), default=UserRole.MEMBER)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    org: Mapped["Org"] = relationship(back_populates="users")


class JiraIntegration(Base):
    """One Jira connection per org. Tokens are encrypted at rest (see backend/db/crypto.py)."""

    __tablename__ = "jira_integrations"
    __table_args__ = (UniqueConstraint("org_id", name="uq_jira_integration_org"),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("orgs.id", ondelete="CASCADE"), index=True)
    base_url: Mapped[str] = mapped_column(String(500))
    cloud_id: Mapped[str] = mapped_column(String(255), default="")
    project_key: Mapped[str] = mapped_column(String(50))
    # OAuth 2.0 (3LO) tokens, Fernet-encrypted before storage.
    encrypted_access_token: Mapped[str] = mapped_column(Text)
    encrypted_refresh_token: Mapped[str] = mapped_column(Text)
    token_expires_at: Mapped[datetime | None] = mapped_column(nullable=True)
    connected_at: Mapped[datetime] = mapped_column(server_default=func.now())

    org: Mapped["Org"] = relationship(back_populates="jira_integration")


class SlackIntegration(Base):
    """One Slack workspace connection per org, from the OAuth install flow."""

    __tablename__ = "slack_integrations"
    __table_args__ = (UniqueConstraint("org_id", name="uq_slack_integration_org"),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("orgs.id", ondelete="CASCADE"), index=True)
    team_id: Mapped[str] = mapped_column(String(50))
    bugs_channel: Mapped[str] = mapped_column(String(255), default="bugs")
    encrypted_bot_token: Mapped[str] = mapped_column(Text)
    installed_at: Mapped[datetime] = mapped_column(server_default=func.now())

    org: Mapped["Org"] = relationship(back_populates="slack_integration")


class Triage(Base):
    """A single triage run's result, replacing outputs/*.json."""

    __tablename__ = "triages"

    id: Mapped[uuid.UUID] = _uuid_pk()
    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("orgs.id", ondelete="CASCADE"), index=True)
    raw_text: Mapped[str] = mapped_column(Text)
    title: Mapped[str] = mapped_column(String(500))
    severity: Mapped[str] = mapped_column(String(10))
    confidence: Mapped[str] = mapped_column(String(20))
    component: Mapped[str] = mapped_column(String(255), default="")
    payload: Mapped[dict] = mapped_column(JSON)  # full TriageOutput dict
    jira_key: Mapped[str | None] = mapped_column(String(50), nullable=True)
    jira_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), index=True)

    org: Mapped["Org"] = relationship(back_populates="triages")
    embedding: Mapped["BugEmbedding"] = relationship(back_populates="triage", uselist=False, cascade="all, delete-orphan")


class BugEmbedding(Base):
    """Replaces outputs/vector_store.json — semantic duplicate detection via pgvector."""

    __tablename__ = "bug_embeddings"

    id: Mapped[uuid.UUID] = _uuid_pk()
    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("orgs.id", ondelete="CASCADE"), index=True)
    triage_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("triages.id", ondelete="CASCADE"), unique=True)
    jira_key: Mapped[str] = mapped_column(String(50))
    jira_url: Mapped[str] = mapped_column(String(500))
    title: Mapped[str] = mapped_column(String(500))
    embedding: Mapped[list[float]] = mapped_column(Vector(EMBEDDING_DIM))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    triage: Mapped["Triage"] = relationship(back_populates="embedding")

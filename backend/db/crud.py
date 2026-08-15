import re
import uuid
from dataclasses import dataclass
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import models
from .crypto import decrypt, encrypt


def get_org_by_slug(db: Session, slug: str) -> Optional[models.Org]:
    return db.scalar(select(models.Org).where(models.Org.slug == slug))


def get_or_create_org(db: Session, slug: str, name: str) -> models.Org:
    org = get_org_by_slug(db, slug)
    if org:
        return org
    org = models.Org(slug=slug, name=name)
    db.add(org)
    db.commit()
    db.refresh(org)
    return org


def get_org_routing_rules(db: Session, org_id: uuid.UUID) -> Optional[dict]:
    """None means the org hasn't configured its own rules — callers fall back
    to rules.py's DEFAULT_RULE_MAPPINGS in that case."""
    org = db.get(models.Org, org_id)
    return org.routing_rules if org else None


def update_org_routing_rules(db: Session, org_id: uuid.UUID, routing_rules: dict) -> models.Org:
    org = db.get(models.Org, org_id)
    org.routing_rules = routing_rules
    db.commit()
    db.refresh(org)
    return org


def _slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return slug or "org"


def create_org_with_unique_slug(db: Session, name: str) -> models.Org:
    """Used by signup — org names aren't unique, so this appends -2, -3, ...
    on collision rather than failing the whole signup over a naming clash."""
    base_slug = _slugify(name)
    slug = base_slug
    suffix = 1
    while get_org_by_slug(db, slug) is not None:
        suffix += 1
        slug = f"{base_slug}-{suffix}"

    org = models.Org(name=name, slug=slug)
    db.add(org)
    db.commit()
    db.refresh(org)
    return org


def get_user_by_email(db: Session, email: str) -> Optional[models.User]:
    return db.scalar(select(models.User).where(models.User.email == email))


def create_user(db: Session, org_id: uuid.UUID, email: str, name: str, role: str, password_hash: str) -> models.User:
    user = models.User(org_id=org_id, email=email, name=name, role=role, password_hash=password_hash)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def upsert_jira_integration(
    db: Session,
    org_id: uuid.UUID,
    base_url: str,
    email: str,
    api_token: str,
    project_key: str,
) -> models.JiraIntegration:
    """Classic email+API-token auth. Encrypts the token before storing."""
    integration = db.scalar(select(models.JiraIntegration).where(models.JiraIntegration.org_id == org_id))
    if integration is None:
        integration = models.JiraIntegration(org_id=org_id)
        db.add(integration)

    integration.base_url = base_url.rstrip("/")
    integration.email = email
    integration.project_key = project_key
    integration.encrypted_access_token = encrypt(api_token)

    db.commit()
    db.refresh(integration)
    return integration


@dataclass
class JiraCreds:
    base_url: str
    email: str
    api_token: str
    project_key: str


def get_jira_creds(db: Session, org_id: uuid.UUID) -> Optional[JiraCreds]:
    integration = db.scalar(select(models.JiraIntegration).where(models.JiraIntegration.org_id == org_id))
    if integration is None or not integration.email:
        return None
    return JiraCreds(
        base_url=integration.base_url,
        email=integration.email,
        api_token=decrypt(integration.encrypted_access_token),
        project_key=integration.project_key,
    )


def get_jira_integration_row(db: Session, org_id: uuid.UUID) -> Optional[models.JiraIntegration]:
    """Raw ORM row, for callers (jira_client.py) that need to tell classic vs OAuth
    auth apart and, for OAuth, mutate the row in place when refreshing tokens."""
    return db.scalar(select(models.JiraIntegration).where(models.JiraIntegration.org_id == org_id))


def store_jira_oauth_integration(
    db: Session,
    org_id: uuid.UUID,
    cloud_id: str,
    base_url: str,
    project_key: str,
    access_token: str,
    refresh_token: str,
    expires_at,
) -> models.JiraIntegration:
    """OAuth 2.0 (3LO) auth. email stays null — that's how jira_client.py tells
    this apart from the classic email+API-token integration."""
    integration = db.scalar(select(models.JiraIntegration).where(models.JiraIntegration.org_id == org_id))
    if integration is None:
        integration = models.JiraIntegration(org_id=org_id)
        db.add(integration)

    integration.email = None
    integration.cloud_id = cloud_id
    integration.base_url = base_url.rstrip("/")
    integration.project_key = project_key
    integration.encrypted_access_token = encrypt(access_token)
    integration.encrypted_refresh_token = encrypt(refresh_token)
    integration.token_expires_at = expires_at

    db.commit()
    db.refresh(integration)
    return integration


def get_slack_integration_row(db: Session, org_id: uuid.UUID) -> Optional[models.SlackIntegration]:
    return db.scalar(select(models.SlackIntegration).where(models.SlackIntegration.org_id == org_id))


def get_slack_integration_by_team_id(db: Session, team_id: str) -> Optional[models.SlackIntegration]:
    """The lookup slack_bot.py actually runs on every incoming event — one Socket
    Mode connection now serves every connected workspace, so each event carries a
    team_id that has to resolve to the right org (and bot token) before anything
    else can happen."""
    return db.scalar(select(models.SlackIntegration).where(models.SlackIntegration.team_id == team_id))


def store_slack_oauth_integration(
    db: Session,
    org_id: uuid.UUID,
    team_id: str,
    bot_user_id: str,
    bot_token: str,
    bugs_channel: str,
) -> models.SlackIntegration:
    integration = get_slack_integration_row(db, org_id)
    if integration is None:
        integration = models.SlackIntegration(org_id=org_id)
        db.add(integration)

    integration.team_id = team_id
    integration.bot_user_id = bot_user_id
    integration.bugs_channel = bugs_channel
    integration.encrypted_bot_token = encrypt(bot_token)

    db.commit()
    db.refresh(integration)
    return integration


def update_slack_bot_token(db: Session, integration_id: uuid.UUID, bot_token: str) -> None:
    """Used by PostgresInstallationStore.save() — Bolt's own hook for persisting
    a (re)installation. Our real write path is store_slack_oauth_integration via
    the /integrations/slack/callback route; this exists so the store still behaves
    correctly if Bolt ever calls save() on its own (e.g. token rotation)."""
    integration = db.get(models.SlackIntegration, integration_id)
    if integration is None:
        return
    integration.encrypted_bot_token = encrypt(bot_token)
    db.commit()


def create_triage(db: Session, org_id: uuid.UUID, raw_text: str, triage: dict) -> models.Triage:
    row = models.Triage(
        org_id=org_id,
        raw_text=raw_text,
        title=triage.get("title", "Untitled"),
        severity=triage.get("severity", "P3"),
        confidence=triage.get("confidence", "Medium"),
        component=triage.get("component", ""),
        payload=triage,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def set_triage_jira_ticket(db: Session, triage_id: uuid.UUID, jira_key: str, jira_url: str) -> None:
    row = db.get(models.Triage, triage_id)
    if row is None:
        return
    row.jira_key = jira_key
    row.jira_url = jira_url
    db.commit()


def store_embedding(
    db: Session,
    org_id: uuid.UUID,
    triage_id: uuid.UUID,
    jira_key: str,
    jira_url: str,
    title: str,
    embedding: list[float],
) -> models.BugEmbedding:
    row = models.BugEmbedding(
        org_id=org_id,
        triage_id=triage_id,
        jira_key=jira_key,
        jira_url=jira_url,
        title=title,
        embedding=embedding,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def find_similar_embedding(
    db: Session,
    org_id: uuid.UUID,
    embedding: list[float],
    similarity_threshold: float,
) -> Optional[dict]:
    """Nearest neighbor within the org via pgvector cosine distance.
    Returns None if the store is empty or nothing clears similarity_threshold.
    """
    distance = models.BugEmbedding.embedding.cosine_distance(embedding)
    stmt = (
        select(models.BugEmbedding, distance.label("distance"))
        .where(models.BugEmbedding.org_id == org_id)
        .order_by(distance)
        .limit(1)
    )
    result = db.execute(stmt).first()
    if result is None:
        return None

    row, dist = result
    similarity = 1 - dist
    if similarity < similarity_threshold:
        return None

    return {
        "jira_key": row.jira_key,
        "jira_url": row.jira_url,
        "title": row.title,
        "similarity": round(similarity * 100, 1),
    }

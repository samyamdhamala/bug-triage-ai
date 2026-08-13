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


def store_slack_oauth_integration(
    db: Session,
    org_id: uuid.UUID,
    team_id: str,
    bot_token: str,
    bugs_channel: str,
) -> models.SlackIntegration:
    integration = get_slack_integration_row(db, org_id)
    if integration is None:
        integration = models.SlackIntegration(org_id=org_id)
        db.add(integration)

    integration.team_id = team_id
    integration.bugs_channel = bugs_channel
    integration.encrypted_bot_token = encrypt(bot_token)

    db.commit()
    db.refresh(integration)
    return integration


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

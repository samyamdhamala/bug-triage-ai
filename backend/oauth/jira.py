"""
Atlassian OAuth 2.0 (3LO) client for Jira Cloud.

Registering an app: https://developer.atlassian.com/console/myapps/
- Add the "Jira API" permission with scopes: read:jira-work, write:jira-work, offline_access
- Set the callback URL to match JIRA_OAUTH_REDIRECT_URI in .env

Why this replaces the classic email+API-token flow: those tokens have no
refresh mechanism, so they just die (revoked, rotated, expired) with no
warning — which is exactly what happened before this was built. OAuth access
tokens expire in ~1 hour by design, but the refresh_token (requested via the
offline_access scope) renews them automatically, indefinitely, as long as the
integration isn't explicitly disconnected.
"""

import os
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

import requests
from sqlalchemy.orm import Session

from ..db import models
from ..db.crypto import decrypt, encrypt

AUTHORIZE_URL = "https://auth.atlassian.com/authorize"
TOKEN_URL = "https://auth.atlassian.com/oauth/token"
ACCESSIBLE_RESOURCES_URL = "https://api.atlassian.com/oauth/token/accessible-resources"
SCOPES = "read:jira-work write:jira-work offline_access"

# Refresh this long before actual expiry so a slow request never straddles
# the token dying mid-flight.
REFRESH_SKEW = timedelta(minutes=2)


def build_authorize_url(state: str) -> str:
    params = {
        "audience": "api.atlassian.com",
        "client_id": os.environ["JIRA_OAUTH_CLIENT_ID"],
        "scope": SCOPES,
        "redirect_uri": os.environ["JIRA_OAUTH_REDIRECT_URI"],
        "state": state,
        "response_type": "code",
        "prompt": "consent",
    }
    return f"{AUTHORIZE_URL}?{urlencode(params)}"


def exchange_code_for_tokens(code: str) -> dict:
    """Returns {access_token, refresh_token, expires_in, ...} on success."""
    response = requests.post(
        TOKEN_URL,
        json={
            "grant_type": "authorization_code",
            "client_id": os.environ["JIRA_OAUTH_CLIENT_ID"],
            "client_secret": os.environ["JIRA_OAUTH_CLIENT_SECRET"],
            "code": code,
            "redirect_uri": os.environ["JIRA_OAUTH_REDIRECT_URI"],
        },
    )
    if response.status_code != 200:
        raise ValueError(f"Jira OAuth token exchange failed {response.status_code}: {response.text}")
    return response.json()


def refresh_tokens(refresh_token: str) -> dict:
    """Returns {access_token, refresh_token, expires_in, ...}. Atlassian rotates
    the refresh token on every use — callers MUST persist the new one, the old
    one stops working immediately."""
    response = requests.post(
        TOKEN_URL,
        json={
            "grant_type": "refresh_token",
            "client_id": os.environ["JIRA_OAUTH_CLIENT_ID"],
            "client_secret": os.environ["JIRA_OAUTH_CLIENT_SECRET"],
            "refresh_token": refresh_token,
        },
    )
    if response.status_code != 200:
        raise ValueError(f"Jira OAuth token refresh failed {response.status_code}: {response.text}")
    return response.json()


def fetch_accessible_resources(access_token: str) -> list[dict]:
    """Returns the list of Jira sites this token can access: [{id (cloud_id), url, name, scopes}, ...]."""
    response = requests.get(
        ACCESSIBLE_RESOURCES_URL,
        headers={"Authorization": f"Bearer {access_token}", "Accept": "application/json"},
    )
    if response.status_code != 200:
        raise ValueError(f"Fetching accessible Jira sites failed {response.status_code}: {response.text}")
    return response.json()


def ensure_fresh_access_token(db: Session, integration: models.JiraIntegration) -> str:
    """Returns a valid access token for this integration, refreshing (and persisting
    the rotated refresh token) first if the current one is expired or about to be."""
    now = datetime.now(timezone.utc)
    expires_at = integration.token_expires_at
    if expires_at is not None and expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)

    if expires_at is not None and expires_at - REFRESH_SKEW > now:
        return decrypt(integration.encrypted_access_token)

    refresh_token = decrypt(integration.encrypted_refresh_token)
    tokens = refresh_tokens(refresh_token)

    new_access_token = tokens["access_token"]
    new_refresh_token = tokens.get("refresh_token", refresh_token)  # rotated; falls back defensively
    expires_in = tokens.get("expires_in", 3600)

    integration.encrypted_access_token = encrypt(new_access_token)
    integration.encrypted_refresh_token = encrypt(new_refresh_token)
    integration.token_expires_at = now + timedelta(seconds=expires_in)
    db.commit()

    return new_access_token

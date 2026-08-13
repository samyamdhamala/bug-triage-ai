import uuid
from typing import Optional

import requests
from requests.auth import HTTPBasicAuth
from sqlalchemy.orm import Session

from .db import crud
from .oauth import jira as jira_oauth

SEVERITY_TO_PRIORITY = {
    "P1": "Highest",
    "P2": "High",
    "P3": "Medium",
    "P4": "Low",
}


def _connection_for_org(db: Session, org_id: uuid.UUID) -> tuple[str, str, str, Optional[HTTPBasicAuth], dict]:
    """Returns (request_base_url, browse_base_url, project_key, auth, extra_headers)
    for the org's Jira integration, whichever auth mode it's using:
    - classic (email set): HTTPBasicAuth directly against the org's own Jira site —
      request and browse URLs are the same host.
    - OAuth 2.0 (integration.encrypted_refresh_token set): Bearer token, requests go
      through api.atlassian.com's proxy host but browse links must still point at the
      real site (integration.base_url), or they 404 for users clicking them.
    Refreshes the OAuth access token transparently if it's expired or close to it.
    """
    integration = crud.get_jira_integration_row(db, org_id)
    if integration is None:
        raise ValueError("No Jira integration configured for this org")

    if integration.email:
        creds = crud.get_jira_creds(db, org_id)
        return creds.base_url, creds.base_url, creds.project_key, HTTPBasicAuth(creds.email, creds.api_token), {}

    if integration.encrypted_refresh_token:
        access_token = jira_oauth.ensure_fresh_access_token(db, integration)
        request_base_url = f"https://api.atlassian.com/ex/jira/{integration.cloud_id}"
        return request_base_url, integration.base_url, integration.project_key, None, {"Authorization": f"Bearer {access_token}"}

    raise ValueError("Jira integration has neither classic credentials nor an OAuth refresh token")


def find_duplicate(db: Session, org_id: uuid.UUID, triage: dict) -> Optional[dict]:
    """Search Jira for an existing open bug with the same component and similar title.
    Returns {"key": ..., "url": ..., "title": ...} if a duplicate is found, else None.
    """
    base_url, browse_base_url, project_key, auth, extra_headers = _connection_for_org(db, org_id)
    headers = {"Accept": "application/json", **extra_headers}

    # Build search terms from title + component + bug_type for broader matching
    STOPWORDS = {"with", "that", "this", "from", "have", "been", "when", "after", "into", "over", "some", "just"}
    all_text = f"{triage.get('title', '')} {triage.get('component', '')} {triage.get('bug_type', '')}"
    seen = set()
    title_words = []
    for w in all_text.lower().split():
        if len(w) > 3 and w not in STOPWORDS and w not in seen:
            seen.add(w)
            title_words.append(w)

    if not title_words:
        return None

    # Use top 3 keywords joined with OR for broader Jira search
    text_clauses = " OR ".join(f'text ~ "{w}"' for w in title_words[:3])
    jql = f'project = {project_key} AND issuetype = Bug AND statusCategory != Done AND ({text_clauses})'

    response = requests.post(
        f"{base_url}/rest/api/3/search/jql",
        json={"jql": jql, "maxResults": 20, "fields": ["summary", "status"]},
        headers={**headers, "Content-Type": "application/json"},
        auth=auth,
    )

    if response.status_code != 200:
        return None

    issues = response.json().get("issues", [])

    for issue in issues:
        existing_title = issue["fields"]["summary"].lower()
        # Check if enough title words overlap
        matches = sum(1 for w in title_words if w in existing_title)
        if matches >= 2:
            issue_key = issue["key"]
            return {
                "key": issue_key,
                "url": f"{browse_base_url}/browse/{issue_key}",
                "title": issue["fields"]["summary"],
            }

    return None


def create_jira_ticket(db: Session, org_id: uuid.UUID, triage: dict) -> dict:
    """Create a Jira issue from a triage result. Returns the created issue key and URL."""
    base_url, browse_base_url, project_key, auth, extra_headers = _connection_for_org(db, org_id)
    headers = {"Accept": "application/json", "Content-Type": "application/json", **extra_headers}

    severity = triage.get("severity", "P3")
    priority = SEVERITY_TO_PRIORITY.get(severity, "Medium")

    repro_steps = triage.get("reproduction_steps", [])
    repro_content = [
        {"type": "listItem", "content": [{"type": "paragraph", "content": [{"type": "text", "text": step}]}]}
        for step in repro_steps
    ]

    description = {
        "type": "doc",
        "version": 1,
        "content": [
            {
                "type": "heading",
                "attrs": {"level": 3},
                "content": [{"type": "text", "text": "Bug Details"}],
            },
            {
                "type": "paragraph",
                "content": [
                    {"type": "text", "text": "Component: ", "marks": [{"type": "strong"}]},
                    {"type": "text", "text": triage.get("component", "Unknown")},
                ],
            },
            {
                "type": "paragraph",
                "content": [
                    {"type": "text", "text": "Affected Users: ", "marks": [{"type": "strong"}]},
                    {"type": "text", "text": triage.get("affected_users", "Unknown")},
                ],
            },
            {
                "type": "paragraph",
                "content": [
                    {"type": "text", "text": "Confidence: ", "marks": [{"type": "strong"}]},
                    {"type": "text", "text": triage.get("confidence", "Unknown")},
                ],
            },
            {
                "type": "heading",
                "attrs": {"level": 3},
                "content": [{"type": "text", "text": "Expected Behavior"}],
            },
            {
                "type": "paragraph",
                "content": [{"type": "text", "text": triage.get("expected_behavior", "")}],
            },
            {
                "type": "heading",
                "attrs": {"level": 3},
                "content": [{"type": "text", "text": "Actual Behavior"}],
            },
            {
                "type": "paragraph",
                "content": [{"type": "text", "text": triage.get("actual_behavior", "")}],
            },
            {
                "type": "heading",
                "attrs": {"level": 3},
                "content": [{"type": "text", "text": "Reproduction Steps"}],
            },
            {"type": "bulletList", "content": repro_content} if repro_content else {
                "type": "paragraph",
                "content": [{"type": "text", "text": "No reproduction steps provided."}],
            },
            {
                "type": "heading",
                "attrs": {"level": 3},
                "content": [{"type": "text", "text": "Priority Reasoning"}],
            },
            {
                "type": "paragraph",
                "content": [{"type": "text", "text": triage.get("priority_reasoning", "")}],
            },
        ],
    }

    payload = {
        "fields": {
            "project": {"key": project_key},
            "summary": f"[{severity}] {triage.get('title', 'Untitled Bug')}",
            "description": description,
            "issuetype": {"name": "Bug"},
            "priority": {"name": priority},
            "labels": [l.replace(" ", "_") for l in triage.get("suggested_labels", [])],
        }
    }

    response = requests.post(
        f"{base_url}/rest/api/3/issue",
        json=payload,
        headers=headers,
        auth=auth,
    )

    if response.status_code not in (200, 201):
        raise ValueError(f"Jira API error {response.status_code}: {response.text}")

    data = response.json()
    issue_key = data["key"]
    issue_url = f"{browse_base_url}/browse/{issue_key}"
    return {"key": issue_key, "url": issue_url}

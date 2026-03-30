import os
from typing import Optional
import requests
from requests.auth import HTTPBasicAuth
from dotenv import load_dotenv

load_dotenv()

SEVERITY_TO_PRIORITY = {
    "P1": "Highest",
    "P2": "High",
    "P3": "Medium",
    "P4": "Low",
}


def find_duplicate(triage: dict) -> Optional[dict]:
    """Search Jira for an existing open bug with the same component and similar title.
    Returns {"key": ..., "url": ..., "title": ...} if a duplicate is found, else None.
    """
    base_url = os.environ["JIRA_BASE_URL"].rstrip("/")
    email = os.environ["JIRA_EMAIL"]
    api_token = os.environ["JIRA_API_TOKEN"]
    project_key = os.environ["JIRA_PROJECT_KEY"]

    auth = HTTPBasicAuth(email, api_token)
    headers = {"Accept": "application/json"}

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
                "url": f"{base_url}/browse/{issue_key}",
                "title": issue["fields"]["summary"],
            }

    return None


def create_jira_ticket(triage: dict) -> dict:
    """Create a Jira issue from a triage result. Returns the created issue key and URL."""
    base_url = os.environ["JIRA_BASE_URL"].rstrip("/")
    email = os.environ["JIRA_EMAIL"]
    api_token = os.environ["JIRA_API_TOKEN"]
    project_key = os.environ["JIRA_PROJECT_KEY"]

    auth = HTTPBasicAuth(email, api_token)
    headers = {"Accept": "application/json", "Content-Type": "application/json"}

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
    issue_url = f"{base_url}/browse/{issue_key}"
    return {"key": issue_key, "url": issue_url}

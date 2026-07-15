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

# Slightly higher threshold for Jira search since we compare full bug text
# against Jira titles only (less context on the Jira side).
JIRA_SIMILARITY_THRESHOLD = 0.72


def find_similar_in_jira(triage: dict) -> Optional[dict]:
    """Semantic duplicate search against open Jira bugs.

    Fetches up to 50 recent open bugs from Jira, embeds their summaries,
    and compares against the incoming triage using cosine similarity.
    Catches duplicates that were created manually and are not yet in the
    local vector store, including paraphrased or differently-worded reports.

    Returns {"key": ..., "url": ..., "title": ..., "similarity": ...} or None.
    """
    from .vector_store import embed_text, cosine_similarity, _bug_to_text

    base_url = os.environ["JIRA_BASE_URL"].rstrip("/")
    email = os.environ["JIRA_EMAIL"]
    api_token = os.environ["JIRA_API_TOKEN"]
    project_key = os.environ["JIRA_PROJECT_KEY"]

    auth = HTTPBasicAuth(email, api_token)
    headers = {"Accept": "application/json", "Content-Type": "application/json"}

    jql = f"project = {project_key} AND issuetype = Bug AND statusCategory != Done ORDER BY created DESC"
    response = requests.post(
        f"{base_url}/rest/api/3/search/jql",
        json={"jql": jql, "maxResults": 50, "fields": ["summary"]},
        headers=headers,
        auth=auth,
    )

    if response.status_code != 200:
        return None

    issues = response.json().get("issues", [])
    if not issues:
        return None

    incoming_text = _bug_to_text(triage)
    if not incoming_text:
        return None

    incoming_embedding = embed_text(incoming_text)

    # Batch embed all Jira summaries at once for efficiency
    summaries = [issue["fields"]["summary"] for issue in issues]
    from .vector_store import _get_model
    summary_embeddings = _get_model().encode(summaries).tolist()

    best_match = None
    best_score = 0.0

    for issue, summary_embedding in zip(issues, summary_embeddings):
        score = cosine_similarity(incoming_embedding, summary_embedding)
        if score > best_score:
            best_score = score
            best_match = issue

    if best_score >= JIRA_SIMILARITY_THRESHOLD and best_match:
        issue_key = best_match["key"]
        return {
            "key": issue_key,
            "url": f"{base_url}/browse/{issue_key}",
            "title": best_match["fields"]["summary"],
            "similarity": round(best_score * 100, 1),
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

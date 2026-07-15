"""
Human feedback loop — stores QA corrections and surfaces them as prompt context.

Corrections are written to outputs/feedback.json as a flat list.
The most recent N entries are injected into the triage prompt so the LLM
can learn from past mistakes without retraining.
"""

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Dict, Any

FEEDBACK_PATH = Path(__file__).parent.parent / "outputs" / "feedback.json"


def _load() -> List[Dict[str, Any]]:
    if not FEEDBACK_PATH.exists():
        return []
    with open(FEEDBACK_PATH, "r") as f:
        return json.load(f)


def _save(entries: List[Dict[str, Any]]) -> None:
    FEEDBACK_PATH.parent.mkdir(exist_ok=True)
    with open(FEEDBACK_PATH, "w") as f:
        json.dump(entries, f, indent=2)


def save_feedback(jira_key: str, comment: str, corrected_by: str = "unknown") -> None:
    """Append a human correction for a previously triaged bug."""
    entries = _load()
    entries.append({
        "jira_key": jira_key.upper(),
        "comment": comment.strip(),
        "corrected_by": corrected_by,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })
    _save(entries)


def load_recent_feedback(n: int = 5) -> List[Dict[str, Any]]:
    """Return the n most recent corrections, newest first."""
    entries = _load()
    return entries[-n:][::-1]


def format_feedback_for_prompt(n: int = 5) -> str:
    """Return a formatted block to inject into the triage prompt, or empty string if none."""
    recent = load_recent_feedback(n)
    if not recent:
        return ""
    lines = [f"- [{e['jira_key']}] \"{e['comment']}\"" for e in recent]
    return (
        "RECENT QA CORRECTIONS (human reviewers flagged these past triage mistakes — "
        "apply these learnings to similar cases):\n"
        + "\n".join(lines)
        + "\n\n"
    )

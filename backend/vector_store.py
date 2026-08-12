"""
Vector similarity store for semantic duplicate detection.
Embeds bug reports using sentence-transformers and compares via pgvector cosine
distance (backend/db/models.py::BugEmbedding). Much more accurate than keyword
matching — catches duplicates even with different wording.
"""

import uuid
from typing import Optional

from sentence_transformers import SentenceTransformer
from sqlalchemy.orm import Session

from .db import crud

MODEL_NAME = "all-MiniLM-L6-v2"  # ~80MB, fast, accurate for semantic similarity; 384-dim
SIMILARITY_THRESHOLD = 0.68  # 0.0 - 1.0, higher = stricter matching

_model = None


def _get_model() -> SentenceTransformer:
    global _model
    if _model is None:
        _model = SentenceTransformer(MODEL_NAME)
    return _model


def _bug_to_text(triage: dict) -> str:
    """Combine the most meaningful fields into one string for embedding."""
    parts = [
        triage.get("title", ""),
        triage.get("component", ""),
        triage.get("actual_behavior", ""),
        triage.get("bug_type", ""),
    ]
    return " ".join(p for p in parts if p).strip()


def find_similar(db: Session, org_id: uuid.UUID, triage: dict) -> Optional[dict]:
    """
    Compare triage against stored embeddings for this org.
    Returns {"jira_key": ..., "jira_url": ..., "title": ..., "similarity": ...} if a
    duplicate is found, else None.
    """
    text = _bug_to_text(triage)
    if not text:
        return None

    embedding = _get_model().encode(text).tolist()
    return crud.find_similar_embedding(db, org_id, embedding, SIMILARITY_THRESHOLD)


def store_embedding(db: Session, org_id: uuid.UUID, triage_id: uuid.UUID, triage: dict, jira_key: str, jira_url: str) -> None:
    """Save a new bug embedding after its Jira ticket is created."""
    text = _bug_to_text(triage)
    if not text:
        return

    embedding = _get_model().encode(text).tolist()
    crud.store_embedding(
        db,
        org_id=org_id,
        triage_id=triage_id,
        jira_key=jira_key,
        jira_url=jira_url,
        title=triage.get("title", ""),
        embedding=embedding,
    )

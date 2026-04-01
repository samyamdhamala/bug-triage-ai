"""
Vector similarity store for semantic duplicate detection.
Embeds bug reports using sentence-transformers and compares via cosine similarity.
Much more accurate than keyword matching — catches duplicates even with different wording.
"""

import json
import os
import numpy as np
from pathlib import Path
from typing import Optional
from sentence_transformers import SentenceTransformer

STORE_PATH = Path(__file__).parent.parent / "outputs" / "vector_store.json"
MODEL_NAME = "all-MiniLM-L6-v2"  # ~80MB, fast, accurate for semantic similarity
SIMILARITY_THRESHOLD = 0.68  # 0.0 - 1.0, higher = stricter matching

_model = None


def _get_model() -> SentenceTransformer:
    global _model
    if _model is None:
        _model = SentenceTransformer(MODEL_NAME)
    return _model


def _load_store() -> list:
    if not STORE_PATH.exists():
        return []
    with open(STORE_PATH, "r") as f:
        return json.load(f)


def _save_store(store: list) -> None:
    STORE_PATH.parent.mkdir(exist_ok=True)
    with open(STORE_PATH, "w") as f:
        json.dump(store, f, indent=2)


def _bug_to_text(triage: dict) -> str:
    """Combine the most meaningful fields into one string for embedding."""
    parts = [
        triage.get("title", ""),
        triage.get("component", ""),
        triage.get("actual_behavior", ""),
        triage.get("bug_type", ""),
    ]
    return " ".join(p for p in parts if p).strip()


def _cosine_similarity(a: list, b: list) -> float:
    va = np.array(a)
    vb = np.array(b)
    return float(np.dot(va, vb) / (np.linalg.norm(va) * np.linalg.norm(vb)))


def find_similar(triage: dict) -> Optional[dict]:
    """
    Compare triage against stored embeddings.
    Returns {"jira_key": ..., "title": ..., "similarity": ...} if duplicate found, else None.
    """
    store = _load_store()
    if not store:
        return None

    model = _get_model()
    text = _bug_to_text(triage)
    if not text:
        return None

    embedding = model.encode(text).tolist()

    best_match = None
    best_score = 0.0

    for entry in store:
        score = _cosine_similarity(embedding, entry["embedding"])
        if score > best_score:
            best_score = score
            best_match = entry

    if best_score >= SIMILARITY_THRESHOLD and best_match:
        return {
            "jira_key": best_match["jira_key"],
            "jira_url": best_match["jira_url"],
            "title": best_match["title"],
            "similarity": round(best_score * 100, 1),
        }

    return None


def store_embedding(triage: dict, jira_key: str, jira_url: str) -> None:
    """Save a new bug embedding after its Jira ticket is created."""
    model = _get_model()
    text = _bug_to_text(triage)
    if not text:
        return

    embedding = model.encode(text).tolist()
    store = _load_store()

    store.append({
        "jira_key": jira_key,
        "jira_url": jira_url,
        "title": triage.get("title", ""),
        "text": text,
        "embedding": embedding,
    })

    _save_store(store)

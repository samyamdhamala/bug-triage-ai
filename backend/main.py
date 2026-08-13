import os
from datetime import datetime, timedelta, timezone

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from .models import BugInput, TriageOutput
from .triage import triage_bug
from .db import crud
from .db.session import get_db
from .oauth import jira as jira_oauth
from .oauth.state import InvalidState, create_state, verify_state

app = FastAPI(title="Bug Triage AI Backend")

# CORS for Streamlit (localhost)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:8501"],  # Streamlit default
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def get_current_org_id(db: Session = Depends(get_db)) -> str:
    """Resolves the org for this request. Single-org placeholder until
    accounts/auth exist — every request currently maps to DEFAULT_ORG_SLUG.
    """
    slug = os.environ.get("DEFAULT_ORG_SLUG", "default")
    org = crud.get_org_by_slug(db, slug)
    if org is None:
        raise HTTPException(status_code=500, detail=f"Org '{slug}' not found — run scripts/seed_default_org.py first")
    return org.id


@app.post("/triage", response_model=TriageOutput)
async def triage_endpoint(input: BugInput, db: Session = Depends(get_db), org_id=Depends(get_current_org_id)):
    try:
        result = triage_bug(db, org_id, input.bug, save_output=True)
        return TriageOutput(**result)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Triage failed: {str(e)}")

@app.get("/integrations/jira/connect")
async def jira_connect(project_key: str, db: Session = Depends(get_db), org_id=Depends(get_current_org_id)):
    """Kicks off the Atlassian OAuth consent flow. project_key is the Jira project
    tickets get filed into — Jira's OAuth grant doesn't imply one, so the org has
    to pick it before redirecting (there's no later step where we ask again)."""
    state = create_state(org_id, project_key)
    return RedirectResponse(jira_oauth.build_authorize_url(state))


@app.get("/integrations/jira/callback")
async def jira_callback(code: str, state: str, db: Session = Depends(get_db)):
    try:
        payload = verify_state(state)
    except InvalidState as e:
        raise HTTPException(status_code=400, detail=str(e))

    try:
        tokens = jira_oauth.exchange_code_for_tokens(code)
        resources = jira_oauth.fetch_accessible_resources(tokens["access_token"])
    except ValueError as e:
        raise HTTPException(status_code=502, detail=str(e))

    if not resources:
        raise HTTPException(status_code=400, detail="No accessible Jira sites for this account — grant access to at least one site during consent")

    # MVP: take the first accessible site. An org with multiple Jira sites will
    # need a picker here eventually; out of scope until that's a real complaint.
    site = resources[0]
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=tokens.get("expires_in", 3600))

    integration = crud.store_jira_oauth_integration(
        db,
        org_id=payload.org_id,
        cloud_id=site["id"],
        base_url=site["url"],
        project_key=payload.project_key,
        access_token=tokens["access_token"],
        refresh_token=tokens["refresh_token"],
        expires_at=expires_at,
    )
    return {"status": "connected", "site": site["url"], "project_key": integration.project_key}


@app.get("/health")
async def health():
    return {"status": "healthy"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)

from datetime import datetime, timedelta, timezone

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from .auth import AuthedUser, create_access_token, get_current_user, hash_password, verify_password
from .models import BugInput, LoginInput, SignupInput, TokenOutput, TriageOutput
from .triage import triage_bug
from .db import crud
from .db.session import get_db
from .oauth import jira as jira_oauth
from .oauth import slack as slack_oauth
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


@app.post("/auth/signup", response_model=TokenOutput)
async def signup(input: SignupInput, db: Session = Depends(get_db)):
    if crud.get_user_by_email(db, input.email) is not None:
        raise HTTPException(status_code=409, detail="An account with this email already exists")

    org = crud.create_org_with_unique_slug(db, input.org_name)
    user = crud.create_user(
        db,
        org_id=org.id,
        email=input.email,
        name=input.name,
        role="admin",  # first user in a new org is its admin
        password_hash=hash_password(input.password),
    )
    token = create_access_token(user.id, user.org_id, user.role)
    return TokenOutput(access_token=token)


@app.post("/auth/login", response_model=TokenOutput)
async def login(input: LoginInput, db: Session = Depends(get_db)):
    user = crud.get_user_by_email(db, input.email)
    if user is None or user.password_hash is None or not verify_password(input.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Incorrect email or password")

    token = create_access_token(user.id, user.org_id, user.role)
    return TokenOutput(access_token=token)


@app.post("/triage", response_model=TriageOutput)
async def triage_endpoint(input: BugInput, db: Session = Depends(get_db), authed: AuthedUser = Depends(get_current_user)):
    try:
        result = triage_bug(db, authed.org_id, input.bug, save_output=True)
        return TriageOutput(**result)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Triage failed: {str(e)}")

@app.get("/integrations/jira/connect")
async def jira_connect(project_key: str, authed: AuthedUser = Depends(get_current_user)):
    """Kicks off the Atlassian OAuth consent flow. project_key is the Jira project
    tickets get filed into — Jira's OAuth grant doesn't imply one, so the org has
    to pick it before redirecting (there's no later step where we ask again)."""
    state = create_state(authed.org_id, {"project_key": project_key})
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
        project_key=payload.data["project_key"],
        access_token=tokens["access_token"],
        refresh_token=tokens["refresh_token"],
        expires_at=expires_at,
    )
    return {"status": "connected", "site": site["url"], "project_key": integration.project_key}


@app.get("/integrations/slack/connect")
async def slack_connect(bugs_channel: str = "bugs", authed: AuthedUser = Depends(get_current_user)):
    """Kicks off the Slack "Add to Slack" OAuth consent flow."""
    state = create_state(authed.org_id, {"bugs_channel": bugs_channel})
    return RedirectResponse(slack_oauth.build_authorize_url(state))


@app.get("/integrations/slack/callback")
async def slack_callback(code: str, state: str, db: Session = Depends(get_db)):
    try:
        payload = verify_state(state)
    except InvalidState as e:
        raise HTTPException(status_code=400, detail=str(e))

    try:
        tokens = slack_oauth.exchange_code_for_tokens(code)
    except ValueError as e:
        raise HTTPException(status_code=502, detail=str(e))

    integration = crud.store_slack_oauth_integration(
        db,
        org_id=payload.org_id,
        team_id=tokens["team"]["id"],
        bot_token=tokens["access_token"],
        bugs_channel=payload.data.get("bugs_channel", "bugs"),
    )
    return {"status": "connected", "team": tokens["team"]["name"], "bugs_channel": integration.bugs_channel}


@app.get("/health")
async def health():
    return {"status": "healthy"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)

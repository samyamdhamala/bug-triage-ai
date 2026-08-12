import os

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session

from .models import BugInput, TriageOutput
from .triage import triage_bug
from .db import crud
from .db.session import get_db

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

@app.get("/health")
async def health():
    return {"status": "healthy"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)

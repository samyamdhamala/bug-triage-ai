# AI-Powered Bug Triage MVP

## Overview
This MVP demonstrates operational leverage through AI by automating the conversion of raw, unstructured bug reports (Slack, email, notes) into structured Jira-style tickets. AI handles repetitive intake, extraction, formatting, and first-pass triage. Humans stay in the loop for low-confidence or high-risk cases via clear confidence scoring and review flags.

**Key Benefits**:
- Standardizes bug intake instantly
- Surfaces uncertainty for human review
- Applies consistent severity rubrics
- Reduces triage time from minutes to seconds

## Architecture
```
bug-triage-ai/
├── backend/     # FastAPI: LLM abstraction, triage logic, rules
├── frontend/    # Streamlit UI for demo
├── sample_data/ # Test inputs
├── outputs/     # Saved triages (JSON)
├── prompt.txt   # Exact LLM instructions
└── ...
```
- **LLM Layer**: Provider-agnostic (OpenAI/Groq/Gemini)
- **Post-LLM Rules**: Deterministic team routing, label injection
- **UI**: Live triage, confidence badges, download

## Setup
1. `cp .env.example .env` and set your API key + LLM_PROVIDER
2. `pip install -r requirements.txt`
3. Terminal 1: `uvicorn backend.main:app --reload --port 8000`
4. Terminal 2: `streamlit run frontend/app.py`

## Usage
- Paste raw bug text or select sample
- Click \"Triage Bug\"
- Review structured output + confidence
- Download JSON if needed

## Supported Providers
- **OpenAI**: GPT-4o-mini recommended (fast, cheap)
- **Groq**: Llama3.1-70B-versatile (very fast)
- **Gemini**: gemini-1.5-flash (good balance)

## Example Input/Output
**Raw**: \"login is not working for a bunch of users. spinner forever after credentials\"

**Output**:
```
Title: Login hangs on spinner after credential entry
Severity: P2
Confidence: High
Component: Auth
Suggested Assignee: Auth Team
Labels: ['urgent-review']
```

## Failure Modes and Human Review
**What AI does well**:
- Extracts structure from messy text
- Applies consistent severity logic
- Flags uncertainty explicitly

**Where it can fail**:
- Vague reports → Low confidence (human review required)
- Generated repro steps are *guesses* (validate before filing)
- Shallow duplicate detection (label-based only)
- Retry only fixes JSON parse errors, not bad reasoning
- Edge cases like multi-bug reports may need splitting

**Confidence Guide**:
- **High**: Safe for engineer queue
- **Medium**: Quick human scan recommended  
- **Low**: Mandatory review before filing

**Always review P1 severity + low-confidence cases.**

## What's Built
- Slack bot: auto-listens to `#bugs` channel + `/triage` slash command
- Auto Jira ticket creation with full structured description
- Duplicate detection: searches open Jira bugs before creating new ticket
- Confidence gate: Low confidence blocks auto-creation, flags for human review

## Roadmap
- Bug trend dashboards
- Feedback loop: learn from engineer edits
- ~~Vector similarity for smarter duplicate detection~~ done ([sentence-transformers](backend/vector_store.py), migrating to pgvector below)
- Auto-regression test generation

## Multi-tenant data layer (in progress)
Moved off flat-file storage (`outputs/*.json`, `vector_store.json`) and single-org
`.env` credentials, onto one Postgres database, scoped by org — still single-tenant
in practice (`DEFAULT_ORG_SLUG`) until real accounts/signup exist, but every table,
credential, and duplicate-detection query already goes through `org_id`.

- **Tables** (`backend/db/models.py`): `orgs`, `users`, `jira_integrations`,
  `slack_integrations`, `triages`, `bug_embeddings`.
- **Embeddings**: `bug_embeddings.embedding` is a pgvector column (384-dim,
  matching `all-MiniLM-L6-v2`) with an HNSW index, replacing `vector_store.json`.
- **Jira auth, two modes** (`backend/jira_client.py` picks whichever an org has):
  - *Classic* — email + API token, seeded once via `scripts/seed_default_org.py`.
    No refresh mechanism; the token just dies eventually with no warning.
  - *OAuth 2.0 (3LO)* (`backend/oauth/jira.py`) — `GET /integrations/jira/connect?project_key=BT`
    starts the Atlassian consent flow; the access token refreshes itself
    indefinitely afterward. This is the one that doesn't go stale.
- **Credentials**: encrypted at rest (`backend/db/crypto.py`, Fernet), never in `.env` per-org.

Setup (free tier):
1. Create a project at [supabase.com](https://supabase.com) (free Postgres + pgvector included).
2. Copy the connection string from *Project Settings → Database → Connection string → URI*,
   swap `postgresql://` for `postgresql+psycopg://`, and set it as `DATABASE_URL` in `.env`.
3. Generate an encryption key: `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`
   and set it as `ENCRYPTION_KEY` in `.env`.
4. Run migrations: `alembic upgrade head`.
5. Either seed classic Jira creds (`python -m scripts.seed_default_org`, after
   setting `JIRA_*` in `.env`) or connect via OAuth (register an app per the
   `JIRA_OAUTH_*` comments in `.env.example`, then hit `/integrations/jira/connect`).

Not yet wired up: Slack is still a single hardcoded bot token
(`SLACK_BOT_TOKEN`/`SLACK_APP_TOKEN`) — no Slack OAuth install flow yet, so
`slack_integrations` exists in the schema but nothing writes to it. Real
multi-tenancy also still needs accounts/login to replace `DEFAULT_ORG_SLUG`.

## Troubleshooting
- API key invalid → 422 error
- Bad JSON from LLM → auto-retry
- Backend not running → Frontend shows connection error


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
`.env` credentials, onto one Postgres database, scoped by org, with real
accounts (`POST /auth/signup`, `POST /auth/login`) resolving `org_id` per
request instead of a hardcoded env var.

- **Tables** (`backend/db/models.py`): `orgs`, `users`, `jira_integrations`,
  `slack_integrations`, `triages`, `bug_embeddings`.
- **Accounts** (`backend/auth.py`) — `POST /auth/signup {org_name, email, password}`
  creates a new org plus its first (admin) user and returns a JWT; `POST /auth/login`
  returns one for existing users. `/triage` and both `/integrations/*/connect`
  endpoints now require `Authorization: Bearer <token>` and act on the caller's
  own org — bcrypt for password hashing, plain JWT bearer sessions, no refresh
  tokens/email verification/password reset (not needed yet, easy to add later).
  `DEFAULT_ORG_SLUG` still exists but now only backs `scripts/seed_default_org.py`
  (classic Jira creds, a dev convenience path that doesn't go through login) —
  Slack resolves its org per-workspace via `team_id` instead (see below).
- **Embeddings**: `bug_embeddings.embedding` is a pgvector column (384-dim,
  matching `all-MiniLM-L6-v2`) with an HNSW index, replacing `vector_store.json`.
- **Jira auth, two modes** (`backend/jira_client.py` picks whichever an org has):
  - *Classic* — email + API token, seeded once via `scripts/seed_default_org.py`.
    No refresh mechanism; the token just dies eventually with no warning.
  - *OAuth 2.0 (3LO)* (`backend/oauth/jira.py`) — `GET /integrations/jira/connect?project_key=BT`
    starts the Atlassian consent flow; the access token refreshes itself
    indefinitely afterward. This is the one that doesn't go stale.
- **Slack, multi-workspace** (`backend/oauth/slack.py`, `backend/oauth/slack_installation_store.py`) —
  `GET /integrations/slack/connect?bugs_channel=bugs` starts the "Add to Slack" OAuth
  flow and stores the resulting bot token per org. `slack_bot.py` runs one process
  with one Socket Mode connection (one app-level token) that serves *every*
  connected workspace — Bolt resolves the right bot token per incoming event via
  `PostgresInstallationStore`, keyed by the event's `team_id`, instead of one
  hardcoded `SLACK_BOT_TOKEN`. (Earlier note here claimed Socket Mode couldn't do
  this without switching to the HTTP Events API — that was wrong; Socket Mode's
  app-level token belongs to the Slack *app*, not to any one workspace
  installation, so events from every installed workspace multiplex over the same
  connection just fine once an installation store is in the loop.) Bot tokens
  don't expire on their own, so unlike Jira there's no refresh step.
- **Credentials**: encrypted at rest (`backend/db/crypto.py`, Fernet), never in `.env` per-org.

Setup (free tier):
1. Create a project at [supabase.com](https://supabase.com) (free Postgres + pgvector included).
2. Copy the connection string from *Project Settings → Database → Connection string → URI*,
   swap `postgresql://` for `postgresql+psycopg://`, and set it as `DATABASE_URL` in `.env`.
3. Generate an encryption key: `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`
   and set it as `ENCRYPTION_KEY` in `.env`.
4. Run migrations: `alembic upgrade head`.
5. Generate a JWT secret: `python -c "import secrets; print(secrets.token_hex(32))"`
   and set it as `JWT_SECRET` in `.env`.
6. Sign up: `POST /auth/signup {"org_name": "Acme", "email": "you@acme.com", "password": "..."}`,
   save the returned `access_token`, and send it as `Authorization: Bearer <token>`
   on `/triage` and the `/integrations/*/connect` calls below.
7. Connect Jira: classic creds (`python -m scripts.seed_default_org`, a separate
   env-based path that doesn't need login) or OAuth (register an app per the
   `JIRA_OAUTH_*` comments in `.env.example`, then hit `/integrations/jira/connect`
   with your bearer token).
8. Optionally connect Slack too: register an app per the `SLACK_OAUTH_*` comments
   (bot scopes: `channels:history`, `channels:read`, `chat:write`, `commands`),
   set `SLACK_APP_TOKEN`/`SLACK_SIGNING_SECRET` from the app's Basic Information
   page, hit `/integrations/slack/connect`, then run `python slack_bot.py`.

Still open: a picker for orgs with multiple accessible Jira sites (currently
takes the first one), and real per-org settings for `rules.py`'s keyword-based
team routing (currently global, not per-org).

## Troubleshooting
- API key invalid → 422 error
- Bad JSON from LLM → auto-retry
- Backend not running → Frontend shows connection error


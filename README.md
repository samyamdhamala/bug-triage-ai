# Bug Triage AI

Converts unstructured bug reports and CI test failures into structured, actionable Jira tickets — automatically, with consistent severity scoring, team routing, and duplicate detection.

Built by a QA Automation Engineer to eliminate the manual triage bottleneck between "bug reported" and "engineer assigned."

---

## What it does

**Input**: A raw Slack message, a free-text bug report, or a JUnit XML file from CI.

**Output**: A structured ticket with severity (P1–P4), component, reproduction steps, assignee team, suggested Jira labels, and a list of test suites to rerun.

**Key behaviours**:
- Low confidence → no auto-ticket, flagged for human review
- P1 severity → always flagged `urgent-review`
- Duplicate bug → dedup check fires before any ticket is created
- QA correction via `/feedback` → injected into next triage prompt automatically

---

## Architecture

```
Raw input (Slack / API / CI)
        │
        ▼
  LLM (Ollama / OpenAI / Groq / Gemini)
  temperature=0.1, structured JSON output enforced
        │
        ▼
  Deterministic Rules Engine
  ├── Team routing (keyword → Auth / Billing / Frontend / Backend / QA)
  ├── Severity bumping ("all users" / "production down" → P1)
  ├── Review flags (low confidence / P1 → human review label)
  └── Test area suggestions (team → relevant test suites to rerun)
        │
        ▼
  Two-layer Duplicate Detection
  ├── Layer 1: Local vector store (sentence-transformers, cosine ≥ 0.68)
  └── Layer 2: Jira semantic search (batch-embed open tickets, cosine ≥ 0.72)
        │
        ▼
  Jira ticket created + embedding stored
        │
        ▼
  Result posted to Slack thread / returned via API
```

---

## Project structure

```
bug-triage-ai/
├── backend/
│   ├── main.py           # FastAPI: POST /triage, POST /triage/ci, GET /health
│   ├── triage.py         # Orchestration: prompt → LLM → parse → rules
│   ├── llm_client.py     # Provider-agnostic LLM wrapper + JSON schema enforcement
│   ├── models.py         # Pydantic schemas (BugInput, TriageOutput, CITriageRequest, ...)
│   ├── rules.py          # Deterministic post-LLM rules (routing, severity, labels, test areas)
│   ├── jira_client.py    # Jira REST API: semantic duplicate search + ticket creation
│   ├── vector_store.py   # Local embedding store (sentence-transformers)
│   ├── ci_parser.py      # JUnit XML parser + bug description builder
│   ├── feedback_store.py # QA correction store + prompt injection
│   └── prompt.txt        # LLM system prompt with severity rubric
├── frontend/
│   └── app.py            # Streamlit UI
├── slack_bot.py          # Slack bot: #bugs listener + /triage + /feedback
├── tests/                # 102 unit tests (pytest)
│   ├── test_rules.py
│   ├── test_dedup.py
│   ├── test_triage.py
│   ├── test_feedback.py
│   └── test_ci_parser.py
├── sample_data/          # Sample bug reports
├── outputs/              # Saved triage JSONs + vector store + feedback log
└── .github/workflows/
    └── ci.yml            # GitHub Actions: install, validate .env.example, run tests
```

---

## Setup

```bash
git clone https://github.com/samyamdhamala/bug-triage-ai.git
cd bug-triage-ai
python -m venv venv && venv/Scripts/activate   # Windows
pip install -r requirements.txt
cp .env.example .env
# Fill in .env (see Configuration section)
```

### Run the API + UI

```bash
# Terminal 1
uvicorn backend.main:app --reload --port 8000

# Terminal 2
streamlit run frontend/app.py
```

### Run the Slack bot

```bash
python slack_bot.py
```

---

## Configuration

```env
# LLM provider — pick one
LLM_PROVIDER=ollama        # options: openai, groq, gemini, ollama

OPENAI_API_KEY=...
GROQ_API_KEY=...
GEMINI_API_KEY=...

# Ollama (local, no key needed)
OLLAMA_BASE_URL=http://localhost:11434/v1
OLLAMA_MODEL=llama3.2

# Slack
SLACK_BOT_TOKEN=xoxb-...
SLACK_APP_TOKEN=xapp-...
SLACK_BUGS_CHANNEL=bugs

# Jira
JIRA_BASE_URL=https://your-org.atlassian.net
JIRA_EMAIL=you@example.com
JIRA_API_TOKEN=...
JIRA_PROJECT_KEY=BUG
```

---

## API endpoints

### `POST /triage`
Triage a single raw bug report.

```bash
curl -X POST http://localhost:8000/triage \
  -H "Content-Type: application/json" \
  -d '{"bug": "Login spinner never stops after entering credentials, started after deploy"}'
```

**Response** (abbreviated):
```json
{
  "title": "Login hangs on spinner after credential entry",
  "severity": "P1",
  "component": "Authentication",
  "suggested_assignee_team": "Auth Team",
  "confidence": "High",
  "suggested_labels": ["urgent-review"],
  "related_test_areas": ["auth_login_flow", "session_management", "sso_flow"]
}
```

### `POST /triage/ci`
Ingest a JUnit XML report from CI and triage each test failure.

```bash
curl -X POST http://localhost:8000/triage/ci \
  -H "Content-Type: application/json" \
  -d '{
    "junit_xml": "<testsuites>...</testsuites>",
    "branch": "main",
    "commit_sha": "abc123",
    "run_url": "https://github.com/org/repo/actions/runs/999",
    "create_tickets": false
  }'
```

**Response**:
```json
{
  "total_failures_found": 2,
  "triaged_count": 2,
  "branch": "main",
  "results": [
    {
      "test_name": "test_login_flow",
      "classname": "tests.test_auth",
      "failure_type": "failure",
      "triage": {
        "severity": "P2",
        "suggested_assignee_team": "Auth Team",
        "related_test_areas": ["auth_login_flow", "session_management"]
      }
    }
  ]
}
```

**Wire into GitHub Actions:**
```yaml
- name: Triage test failures
  if: failure()
  run: |
    curl -X POST http://your-server:8000/triage/ci \
      -H "Content-Type: application/json" \
      -d "{
        \"junit_xml\": $(cat test-results.xml | python -c 'import sys,json; print(json.dumps(sys.stdin.read()))'),
        \"branch\": \"${{ github.ref_name }}\",
        \"commit_sha\": \"${{ github.sha }}\",
        \"run_url\": \"${{ github.server_url }}/${{ github.repository }}/actions/runs/${{ github.run_id }}\",
        \"create_tickets\": true
      }"
```

Supports JUnit XML from pytest, JUnit, TestNG, Mocha, and any framework with `--junit-xml` output.

### `GET /health`
```json
{"status": "healthy"}
```

---

## Slack commands

| Command | Description |
|---------|-------------|
| Post any message in `#bugs` | Auto-triaged in thread |
| `/triage <bug description>` | Triage from any channel |
| `/feedback BUG-42 <correction>` | Save a QA correction for future triages |

**Feedback loop**: corrections saved via `/feedback` are injected into the LLM prompt on the next triage, so the model learns from QA reviewer judgment without retraining.

---

## Supported LLM providers

| Provider | Model | JSON enforcement |
|----------|-------|-----------------|
| OpenAI | gpt-4o-mini | Strict schema (structured outputs) |
| Groq | llama-3.3-70b-versatile | `json_object` mode |
| Gemini | gemini-1.5-pro | `application/json` MIME |
| Ollama | llama3.2 (configurable) | `json_object` mode |

All providers are swappable with a single `.env` change.

---

## Tests

```bash
pytest tests/ -v
# 102 tests covering: rules engine, dedup pipeline,
# structured output parsing, feedback store, CI XML parser
```

CI runs automatically on every push via GitHub Actions (`.github/workflows/ci.yml`).

---

## Failure modes and human oversight

| Situation | Behaviour |
|-----------|-----------|
| Vague report | Low confidence → no auto-ticket, flagged for human review |
| P1 severity | Always flagged `urgent-review` regardless of confidence |
| Generated repro steps | Prefixed `[generated]` — validate before filing |
| Multi-bug report | Triages most severe, notes "contains multiple issues" |
| Duplicate detected | Similarity score shown, no new ticket created |
| LLM returns bad JSON | Clear error surfaced (structured outputs make this rare) |

---

## Roadmap

- Metrics dashboard: bugs triaged per day, severity distribution, routing accuracy
- Confidence calibration: surface where LLM misroutes most often from feedback log
- Bulk triage from CSV export
- Postgres persistence (replace flat JSON output files)

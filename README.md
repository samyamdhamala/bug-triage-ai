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
- Vector similarity for smarter duplicate detection
- Auto-regression test generation

## Troubleshooting
- API key invalid → 422 error
- Bad JSON from LLM → auto-retry
- Backend not running → Frontend shows connection error


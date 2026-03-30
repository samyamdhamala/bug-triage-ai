# Bug Triage AI — Interview Prep Document
**Role:** Eng Ops — Bug Ticketing + QA + AI Workflows
**Candidate:** Samyam Dhamala
**Date:** March 29, 2026

---

## What You Built — One Paragraph

A fully automated bug triage system that listens to a Slack channel, converts raw unstructured bug reports into structured Jira tickets using AI, and applies deterministic rules for severity, team routing, and duplicate detection. It runs end-to-end without any human involvement for high-confidence reports, and flags low-confidence or high-severity cases for human review before acting. Built in Python using a local LLM (Ollama/Llama 3.2), FastAPI, Slack Bolt, and the Jira REST API.

---

## The Problem It Solves

Bug reports come in as noise — a Slack message, a vague sentence, sometimes just a screenshot. Someone has to:
- Read it and decide severity
- Figure out which team owns it
- Write it up with proper context
- Create the Jira ticket
- Check if it's already been reported

That takes **3–5 minutes per bug**, it's inconsistent, and it only happens if someone remembers to do it.

**This system does all of that in under 10 seconds, automatically, every time.**

---

## How It Works — End to End

```
Someone posts a bug in #bugs (naturally, no form, no command)
        ↓
Bot auto-detects the message
        ↓
LLM extracts: title, severity, component, affected users,
              repro steps, expected/actual behavior, confidence
        ↓
Deterministic rules apply:
  - Keyword → team routing (login → Auth Team, payment → Billing Team)
  - "all users" / "revenue" → severity bump to P1
  - Low confidence → flag for human review
        ↓
Confidence gate:
  - High/Medium → check for duplicates → create Jira ticket
  - Low → post result but NO ticket, flagged for human review
        ↓
Duplicate check:
  - Searches open Jira bugs for keyword overlap
  - Match found → link existing ticket, skip creation
  - No match → create new Jira ticket with full structured content
        ↓
Thread reply in Slack with full triage + Jira link
```

---

## Files Built

| File | Purpose |
|------|---------|
| `backend/prompt.txt` | LLM prompt — severity rubric, JSON schema, confidence instructions |
| `backend/llm_client.py` | Provider-agnostic LLM wrapper (OpenAI / Groq / Gemini / Ollama) |
| `backend/triage.py` | Core orchestration — prompt → LLM → parse → validate → rules |
| `backend/rules.py` | Deterministic post-LLM rules — routing, severity bumping, review flags |
| `backend/models.py` | Pydantic schema — enforces strict output structure |
| `backend/jira_client.py` | Jira REST API — create tickets, find duplicates |
| `slack_bot.py` | Slack bot — auto-listen mode + /triage slash command |
| `frontend/app.py` | Streamlit visual UI |

---

## Tools & Technologies

| Tool | Why Used |
|------|---------|
| Python | Core language |
| FastAPI | Backend API server |
| Streamlit | Visual demo UI |
| Ollama + Llama 3.2 | Local LLM — no API cost, offline, private |
| Groq | Fast cloud LLM alternative (also configured) |
| Pydantic | Validates LLM output schema — rejects malformed JSON |
| slack-bolt | Slack bot framework — auto-listen + slash commands |
| Jira REST API | Auto ticket creation + duplicate search |
| python-dotenv | Config management |

---

## Key Design Decisions (Be Ready to Explain These)

### 1. Two-Layer Architecture: LLM + Deterministic Rules
The LLM handles extraction and reasoning. Deterministic rules (in `rules.py`) handle team routing and severity bumping.

**Why separate?**
Rules are auditable, testable, and don't hallucinate. You can read them, change them, argue with them without touching the AI. The LLM does what it's good at (understanding language), rules do what they're good at (consistency).

### 2. Confidence Score as the Human-in-the-Loop Gate
Low confidence = no auto-creation, flagged for review.
High/Medium confidence = auto-create ticket.

**Why?**
The system knows what it doesn't know. It never pretends to be certain when it isn't. This is the most important trust mechanism.

### 3. Temperature = 0.1
Near-deterministic. Same input gives same output every time. Bug triage needs consistency, not creativity.

### 4. Provider-Agnostic LLM Backend
One line in `.env` switches between OpenAI, Groq, Gemini, or local Ollama.

**Why?**
Cost flexibility, no vendor lock-in. Currently runs on Ollama locally — zero API cost.

### 5. Pydantic Validation
Every LLM response is validated against a strict schema. If the output is malformed, it retries with a simpler prompt. If that fails, it flags for human review.

**Why?**
LLMs occasionally return garbage. Never let bad output silently become a bad ticket.

---

## Demo Script (15 Minutes)

### Opening (2 min)
> "Bug reports come in as noise. Someone has to read it, decide severity, route it, write it up, and create a ticket. That takes 3–5 minutes per bug, it's inconsistent, and the quality depends on who's doing it. I built a system that does all of that in under 10 seconds — and it's designed to know when to trust itself and when to ask for a human."

### Demo 1 — Auto-triage (3 min)
Post in #bugs:
```
hey team, login is totally broken on safari 17 on mac. the spinner just hangs
after clicking submit. console shows a CORS error. works fine on chrome.
affects our whole design team (~12 people). broken since yesterday. - sarah
```
Walk through: severity, team routing, confidence, Jira link (click it live).

### Demo 2 — Human-in-the-loop (2 min)
Post:
```
something is wrong with the dashboard, numbers look off
```
Point out: Low confidence, no ticket created, flagged for review.
> "The system knows what it doesn't know."

### Demo 3 — Duplicate detection (2 min)
Post:
```
users keep getting stuck on the login page on safari, submit button spins
forever. seems like a CORS issue. about 12 people affected.
```
Point out: Existing ticket detected, no duplicate created, link shown.

### Demo 4 — P1 urgent (2 min)
Post:
```
payments are completely down for all users. every checkout attempt fails
with a 500 error. started 10 minutes ago. revenue impact.
```
Point out: Severity bumped to P1 by deterministic rule (revenue + all users keywords), urgent-review flag added.

### Architecture Walk (3 min)
Open `rules.py` — show the two-layer design.
Open `prompt.txt` — show the severity rubric and JSON schema.

### Failure Modes — say this unprompted (1 min)
> "Vague one-liners get Low confidence. Two bugs in one message need manual splitting. Duplicate detection is keyword-based — misses duplicates with totally different wording. Vector similarity is the fix I've designed but not built yet. Severity rubric is a baseline — you'd tune it from historical data in production."

---

## Anticipated Questions & Answers

**"Why not just use a form?"**
> Forms require discipline people don't have in a crisis. When something breaks, people open Slack and type. This meets them where they already are — zero new process for the reporter.

**"How do you handle the LLM getting it wrong?"**
> Two ways: confidence score flags uncertain outputs before a ticket is created, and deterministic rules catch clear cases regardless — revenue + all users always = P1.

**"What stops junk tickets from being created?"**
> Three gates: Pydantic validation rejects malformed outputs, Low confidence blocks auto-creation, messages under 20 characters are ignored.

**"How would you extend this to email or other sources?"**
> The triage logic is fully decoupled. The Slack bot just calls `triage_bug()`. An email poller would be another adapter calling the same function. Same for GitHub issues — core doesn't change.

**"What's the risk of P1 tickets auto-created without human review?"**
> P1s get an urgent-review flag and the confidence gate still applies. In production I'd also add a Slack ping to oncall for P1s — escalate but don't act unilaterally.

**"Have you run this in production?"**
> Working prototype built for this demo. Architecture is production-minded: audit trail of every triage saved to disk, Pydantic validation, human review gates. What I'd harden: rate limiting, API auth, and the feedback loop.

**"What's the feedback loop look like?"**
> When a human corrects a triage — changes severity or reassigns — that gets logged as a correction. Those corrections become few-shot examples in the prompt over time. Accuracy compounds.

**"Why local LLM / Ollama?"**
> No API cost, runs offline, full data privacy. Llama 3.2 handles structured extraction well for this use case. Switching to OpenAI is a one-line config change.

**"How does this scale to 50 bugs a day?"**
> The bottleneck is the human review queue for Low confidence items. I'd add a dashboard showing pending reviews prioritized by severity. High volume makes the automation more valuable, not less.

**"What would you do differently?"**
> Enforce JSON schema at the API level using OpenAI structured outputs — eliminates the retry logic entirely. And I'd build the feedback loop from day one so the system improves as it's used.

---

## QA for Client-Facing Features — Prepared Answer

**If asked: "How would you approach QA for client-facing features?"**

> "I'd apply the same AI-native pattern here. The goal is to catch regressions and data integrity issues before they reach clients — not after.
>
> Concretely, my approach is three layers:
>
> **1. Edge case generation with AI**
> Before a feature ships, I'd feed the spec or PR description to an LLM and ask it to generate edge cases: boundary values, invalid inputs, unusual user flows, data combinations that are likely to break. This is where AI adds real leverage — a human might think of 10 edge cases, the LLM surfaces 50 in seconds. I'd review and trim, not rubber-stamp.
>
> **2. Data integrity checks**
> For client-facing data (dashboards, exports, reports), I'd build automated assertions: row counts match between source and display, no nulls in required fields, totals reconcile. These run on real data snapshots before each deploy. LLM helps write the assertions from the data schema — the checks themselves are deterministic.
>
> **3. Structured output comparison**
> For features that produce structured output (exports, API responses, generated reports), I'd store a baseline of expected outputs and diff against new deploys. Differences get flagged — an LLM then classifies whether the diff is a regression or an intentional change, with confidence scoring. Same human-in-the-loop pattern as the bug triage system.
>
> The through-line: AI handles the volume and surface area, humans review the flagged cases. I'm not replacing the QA judgment call — I'm making sure nothing slips through unexamined."

**If pushed on data integrity specifically:**
> "For B2B SaaS, the scariest bugs are silent data bugs — numbers that look right but aren't. I'd prioritize automated reconciliation checks on anything a client sees in a dashboard or report. The LLM helps me generate the checks fast; the checks themselves run deterministically every deploy."

**If pushed on what you'd build first:**
> "I'd start by shadowing one sprint of releases — every client-facing change that ships. I'd document where QA happens today, where it doesn't, and what broke in the last 90 days. Then I'd build one automated check for the highest-risk surface first. Prove the pattern, then scale it."

---

## How This Fits the Role

| Role Requirement | How This Addresses It |
|---|---|
| Bug ticketing — intake, triage, classification | Fully automated: Slack → structured Jira ticket with severity, team, labels |
| Making sure right things reach engineering in right order | Severity rubric + deterministic rules ensure consistent prioritization |
| Operational leverage through AI | One person handles 10x volume. AI does repetitive work, human owns judgment calls |
| Stays in the loop at decision points requiring judgment | Confidence gate + human review flags = human only reviews what matters |
| QA for client-facing features | Same architecture extends to automated regression testing — next build |
| Ad hoc data pulls | All bugs structured and queryable in Jira by severity, team, component |

---

## Where It Falls Short (Own This)

- Vague reports → Low confidence → human review (by design, but adds queue)
- Multi-bug reports need manual splitting
- Duplicate detection is keyword-based — misses semantic duplicates
- Severity rubric needs calibration against real historical data
- No rate limiting or API auth (needs hardening for prod)
- Generated repro steps are guesses, not validated

**Next builds:**
1. Vector similarity for smarter duplicate detection
2. Feedback loop — human corrections improve the prompt over time
3. QA integration — structured regression tests against new deploys

---

## Your Questions for Them

1. "What does the current bug intake process look like today — where does the most time get lost?"
2. "When you say QA for client-facing features — are you catching regressions pre-deploy or post-deploy?"
3. "How do engineering and ops hand off today — is there a defined SLA for bug response?"
4. "What does good look like in 90 days for this role?"
5. "You mentioned AI is load-bearing in how you operate — what does that look like day to day for this role?"

---

## Quick Reference — Sample Inputs for Live Demo

**1. Normal bug (creates ticket):**
```
hey team, login is totally broken on safari 17 on mac. the spinner just hangs after
clicking submit. console shows a CORS error. works fine on chrome. affects our whole
design team (~12 people). broken since yesterday. - sarah
```

**2. Vague report (Low confidence, no ticket):**
```
something is wrong with the dashboard, numbers look off
```

**3. Duplicate (links existing ticket, no new ticket):**
```
users keep getting stuck on the login page on safari, submit button spins forever.
seems like a CORS issue. about 12 people affected.
```

**4. P1 urgent (severity bump, urgent-review flag):**
```
payments are completely down for all users. every checkout attempt fails with a 500
error. started 10 minutes ago. revenue impact.
```

**5. Different bug (creates new ticket):**
```
checkout is broken for users with promo codes. the discount applies but the final
charge is still full price. reproducible every time. affects anyone using a coupon.
```

---

*Good luck. You've built the thing. Now just show it.*

import logging
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from .models import BugInput, TriageOutput, CITriageRequest, CITriageResponse, CITriageResult
from .triage import triage_bug
from .ci_parser import parse_junit_xml, build_bug_description

logger = logging.getLogger(__name__)

app = FastAPI(title="Bug Triage AI")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:8501"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health():
    return {"status": "healthy"}


@app.post("/triage", response_model=TriageOutput)
async def triage_endpoint(input: BugInput):
    try:
        result = triage_bug(input.bug, save_output=True)
        return TriageOutput(**result)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Triage failed: {str(e)}")


@app.post("/triage/ci", response_model=CITriageResponse)
async def triage_ci(request: CITriageRequest):
    """Ingest a JUnit XML report from CI and triage each test failure.

    Accepts the standard JUnit XML format produced by pytest (--junit-xml),
    JUnit, TestNG, Mocha, and most other test frameworks.

    Each failure is converted into a structured bug description and run through
    the full triage pipeline: LLM → deterministic rules → team routing →
    test area suggestions. Optionally creates Jira tickets.

    Example curl from GitHub Actions:
        curl -X POST http://localhost:8000/triage/ci \\
          -H "Content-Type: application/json" \\
          -d '{"junit_xml": "<testsuites>...</testsuites>",
               "branch": "main",
               "commit_sha": "${{ github.sha }}",
               "run_url": "${{ github.server_url }}/${{ github.repository }}/actions/runs/${{ github.run_id }}"}'
    """
    try:
        failures = parse_junit_xml(request.junit_xml)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    total_found = len(failures)
    to_triage = failures[: request.max_failures]

    results = []
    for failure in to_triage:
        bug_text = build_bug_description(
            failure,
            branch=request.branch,
            commit_sha=request.commit_sha,
            run_url=request.run_url,
        )

        try:
            triage = triage_bug(bug_text, save_output=True)
        except Exception as e:
            logger.warning(f"Triage failed for {failure['classname']}::{failure['test_name']}: {e}")
            continue

        jira_ticket = None
        if request.create_tickets:
            try:
                from .jira_client import create_jira_ticket, find_similar_in_jira
                from .vector_store import find_similar, store_embedding
                if not find_similar(triage) and not find_similar_in_jira(triage):
                    ticket = create_jira_ticket(triage)
                    store_embedding(triage, ticket["key"], ticket["url"])
                    jira_ticket = ticket["key"]
            except Exception as e:
                logger.warning(f"Jira ticket creation failed: {e}")

        results.append(CITriageResult(
            test_name=failure["test_name"],
            classname=failure["classname"],
            failure_type=failure["failure_type"],
            failure_message=failure["failure_message"],
            triage=triage,
            jira_ticket=jira_ticket,
        ))

    return CITriageResponse(
        total_failures_found=total_found,
        triaged_count=len(results),
        branch=request.branch,
        commit_sha=request.commit_sha,
        run_url=request.run_url,
        results=results,
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)

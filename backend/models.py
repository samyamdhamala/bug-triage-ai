from pydantic import BaseModel, Field, validator
from typing import Any, Dict, List, Optional
from enum import Enum

class Severity(str, Enum):
    P1 = "P1"
    P2 = "P2"
    P3 = "P3"
    P4 = "P4"

class Confidence(str, Enum):
    HIGH = "High"
    MEDIUM = "Medium"
    LOW = "Low"

class BugInput(BaseModel):
    bug: str = Field(..., min_length=1, description="Raw unstructured bug report")

class TriageOutput(BaseModel):
    title: str = Field(..., min_length=5)
    severity: Severity
    component: str
    bug_type: str = ""
    affected_users: str = ""
    reproduction_steps: List[str] = Field(default_factory=list)
    expected_behavior: str = ""
    actual_behavior: str = ""
    suggested_labels: List[str] = Field(default_factory=list)
    priority_reasoning: str = ""
    suggested_assignee_team: str
    confidence: Confidence
    related_test_areas: List[str] = Field(default_factory=list)

    class Config:
        extra = 'ignore'


class CITriageRequest(BaseModel):
    junit_xml: str = Field(..., description="JUnit XML string from CI test run")
    branch: str = ""
    commit_sha: str = ""
    run_url: str = ""
    max_failures: int = Field(default=10, ge=1, le=50, description="Cap on failures to triage per run")
    create_tickets: bool = False


class CITriageResult(BaseModel):
    test_name: str
    classname: str
    failure_type: str
    failure_message: str
    triage: Dict[str, Any]
    jira_ticket: Optional[str] = None


class CITriageResponse(BaseModel):
    total_failures_found: int
    triaged_count: int
    branch: str
    commit_sha: str
    run_url: str
    results: List[CITriageResult]


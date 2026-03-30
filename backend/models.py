from pydantic import BaseModel, Field, validator
from typing import List
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

    class Config:
        extra = 'ignore'


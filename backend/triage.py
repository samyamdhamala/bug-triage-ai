import json
import uuid
import logging
from pathlib import Path
from typing import Dict, Any

from dotenv import load_dotenv
from pydantic import ValidationError
from sqlalchemy.orm import Session

from .models import TriageOutput
from .llm_client import generate_structured_ticket
from .rules import enhance_triage
from .db import crud

load_dotenv()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

PROMPT_PATH = Path(__file__).parent / 'prompt.txt'

def load_prompt() -> str:
    '''Load prompt template from file.'''
    if not PROMPT_PATH.exists():
        raise FileNotFoundError(f"Prompt file missing: {PROMPT_PATH}")
    with open(PROMPT_PATH, 'r') as f:
        return f.read()

def parse_json_or_retry(response: str, original_bug: str = None) -> Dict[str, Any]:
    try:
        start = response.find('{')
        end = response.rfind('}') + 1
        json_str = response[start:end] if start != -1 else response
        return json.loads(json_str)
    except json.JSONDecodeError as e:
        logger.warning(f"JSON parse failed: {e}. Retrying with simple prompt.")
        bug_to_use = original_bug if original_bug else response[:1000]
        simple_prompt = f'''Convert this bug report to valid JSON. Return ONLY the JSON, no markdown.

Bug report: {bug_to_use}

Required fields: title, severity (P1-P4), component, bug_type, affected_users, reproduction_steps (array), expected_behavior, actual_behavior, suggested_labels (array), priority_reasoning, suggested_assignee_team, confidence (High/Medium/Low).'''
        retry_response = generate_structured_ticket(simple_prompt)
        try:
            start = retry_response.find('{')
            end = retry_response.rfind('}') + 1
            json_str = retry_response[start:end] if start != -1 else retry_response
            return json.loads(json_str)
        except json.JSONDecodeError:
            raise ValueError("Both initial and retry JSON parsing failed. LLM output invalid.")

def triage_bug(db: Session, org_id: uuid.UUID, raw_text: str, save_output: bool = False) -> Dict[str, Any]:
    '''Main triage function. Persists the result as a Triage row when save_output=True,
    returning the enhanced triage dict plus an internal "_triage_id" for callers that
    go on to create a Jira ticket / store an embedding (jira_client.py, vector_store.py).

    Failure modes (for humans):
    - Vague reports -> low confidence (review required)
    - Generated repro steps are guesses, not confirmed
    - Duplicate detection shallow (labels only)
    - Retry fixes JSON only, not bad reasoning
    - Severity may need human adjustment
    '''
    if not raw_text.strip():
        raise ValueError("Bug text cannot be empty")

    prompt_template = load_prompt()
    prompt = prompt_template.replace('{{RAW_INPUT}}', raw_text)

    # LLM call
    llm_response = generate_structured_ticket(prompt)
    logger.info("LLM response received")

    # Parse + validate
    triage_data = parse_json_or_retry(llm_response, original_bug=raw_text)
    try:
        output = TriageOutput(**triage_data)
    except ValidationError as e:
        logger.error(f"Pydantic validation failed: {e}")
        raise ValueError(f"Invalid triage structure: {e}")

    # Rule enhancements
    routing_rules = crud.get_org_routing_rules(db, org_id)
    enhanced = enhance_triage(output.model_dump(), routing_rules)

    # Persist
    if save_output:
        triage_row = crud.create_triage(db, org_id=org_id, raw_text=raw_text, triage=enhanced)
        logger.info(f"Saved triage {triage_row.id} for org {org_id}")
        enhanced['_triage_id'] = triage_row.id

    return enhanced

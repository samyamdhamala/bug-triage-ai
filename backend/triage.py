import json
import os
from datetime import datetime
from typing import Dict, Any
from pathlib import Path
import logging

from dotenv import load_dotenv
from pydantic import ValidationError

from .models import TriageOutput
from .llm_client import generate_structured_ticket
from .rules import enhance_triage

load_dotenv()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

PROMPT_PATH = Path(__file__).parent / 'prompt.txt'
OUTPUTS_DIR = Path(__file__).parent.parent / 'outputs'
OUTPUTS_DIR.mkdir(exist_ok=True)

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

def triage_bug(raw_text: str, save_output: bool = False) -> Dict[str, Any]:
    '''Main triage function.

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
    enhanced = enhance_triage(output.model_dump())
    
    # Save if requested
    if save_output:
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        output_path = OUTPUTS_DIR / f'triaged_{timestamp}.json'
        with open(output_path, 'w') as f:
            json.dump(enhanced, f, indent=2)
        logger.info(f"Saved to {output_path}")
    
    return enhanced


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
from .feedback_store import format_feedback_for_prompt

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

def parse_llm_response(response: str) -> Dict[str, Any]:
    """Parse the LLM JSON response.

    All providers now return valid JSON via structured output modes, so a
    straight json.loads is sufficient. A JSONDecodeError here means the
    provider ignored the format constraint — surface it clearly rather than
    masking it with a second LLM call.
    """
    try:
        return json.loads(response)
    except json.JSONDecodeError as e:
        raise ValueError(f"LLM returned invalid JSON (provider may not support structured outputs): {e}")

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
    feedback_block = format_feedback_for_prompt(n=5)
    prompt = prompt_template.replace('{{RAW_INPUT}}', raw_text)
    if feedback_block:
        prompt = prompt.replace("BUG REPORT:", feedback_block + "BUG REPORT:", 1)
    
    # LLM call
    llm_response = generate_structured_ticket(prompt)
    logger.info("LLM response received")
    
    # Parse + validate
    triage_data = parse_llm_response(llm_response)
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


import os
from dotenv import load_dotenv
from typing import Any
import openai
import google.generativeai as genai
import httpx

load_dotenv()

PROVIDERS = ['openai', 'groq', 'gemini', 'ollama']

# JSON schema enforced at the API level for OpenAI (strict mode).
# Other providers use json_object mode which guarantees valid JSON but not schema.
TRIAGE_JSON_SCHEMA = {
    "name": "triage_output",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "title":                  {"type": "string"},
            "severity":               {"type": "string", "enum": ["P1", "P2", "P3", "P4"]},
            "component":              {"type": "string"},
            "bug_type":               {"type": "string"},
            "affected_users":         {"type": "string"},
            "reproduction_steps":     {"type": "array", "items": {"type": "string"}},
            "expected_behavior":      {"type": "string"},
            "actual_behavior":        {"type": "string"},
            "suggested_labels":       {"type": "array", "items": {"type": "string"}},
            "priority_reasoning":     {"type": "string"},
            "suggested_assignee_team":{"type": "string"},
            "confidence":             {"type": "string", "enum": ["High", "Medium", "Low"]},
        },
        "required": [
            "title", "severity", "component", "bug_type", "affected_users",
            "reproduction_steps", "expected_behavior", "actual_behavior",
            "suggested_labels", "priority_reasoning", "suggested_assignee_team", "confidence",
        ],
        "additionalProperties": False,
    },
}


def get_llm_client(provider: str) -> Any:
    provider = provider.lower()
    if provider not in PROVIDERS:
        raise ValueError(f"Unsupported LLM provider: {provider}. Choose from {PROVIDERS}")

    if provider == 'openai':
        api_key = os.getenv('OPENAI_API_KEY')
        if not api_key:
            raise ValueError("OPENAI_API_KEY not set in .env")
        return openai.OpenAI(api_key=api_key), 'gpt-4o-mini'

    elif provider == 'groq':
        api_key = os.getenv('GROQ_API_KEY')
        if not api_key:
            raise ValueError("GROQ_API_KEY not set in .env")
        http_client = httpx.Client(transport=httpx.HTTPTransport(retries=0))
        client = openai.OpenAI(
            base_url="https://api.groq.com/openai/v1",
            api_key=api_key,
            http_client=http_client,
        )
        return client, 'llama-3.3-70b-versatile'

    elif provider == 'gemini':
        api_key = os.getenv('GEMINI_API_KEY')
        if not api_key:
            raise ValueError("GEMINI_API_KEY not set in .env")
        genai.configure(api_key=api_key)
        return genai.GenerativeModel('gemini-1.5-pro'), None

    elif provider == 'ollama':
        base_url = os.getenv('OLLAMA_BASE_URL', 'http://localhost:11434/v1')
        http_client = httpx.Client(base_url=base_url)
        client = openai.OpenAI(base_url=base_url, api_key='ollama', http_client=http_client)
        return client, os.getenv('OLLAMA_MODEL', 'llama3.2')


def generate_structured_ticket(prompt: str) -> str:
    """Call the configured LLM and return a JSON string.

    OpenAI: schema-enforced (strict mode) — output is guaranteed valid JSON
    matching TRIAGE_JSON_SCHEMA. Parse failures are impossible.

    Groq/Ollama: json_object mode — guaranteed valid JSON, schema adherence
    depends on the model following the prompt.

    Gemini: application/json MIME type — guaranteed valid JSON.
    """
    provider = os.getenv('LLM_PROVIDER', 'openai').lower()
    client, model_name = get_llm_client(provider)

    if provider == 'openai':
        response = client.chat.completions.create(
            model=model_name,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
            max_completion_tokens=2000,
            response_format={"type": "json_schema", "json_schema": TRIAGE_JSON_SCHEMA},
        )
        return response.choices[0].message.content.strip()

    elif provider == 'groq':
        response = client.chat.completions.create(
            model=model_name,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
            max_completion_tokens=2000,
            response_format={"type": "json_object"},
        )
        return response.choices[0].message.content.strip()

    elif provider == 'gemini':
        response = client.generate_content(
            prompt,
            generation_config=genai.types.GenerationConfig(
                temperature=0.1,
                max_output_tokens=2000,
                response_mime_type="application/json",
            ),
        )
        return response.text.strip()

    elif provider == 'ollama':
        response = client.chat.completions.create(
            model=model_name,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
            max_completion_tokens=2000,
            response_format={"type": "json_object"},
        )
        return response.choices[0].message.content.strip()

    raise ValueError("Unhandled provider")

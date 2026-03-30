import os
from dotenv import load_dotenv
from typing import Dict, Any
import openai
import google.generativeai as genai
import json
import requests
import httpx

load_dotenv()

PROVIDERS = ['openai', 'groq', 'gemini', 'ollama']

def get_llm_client(provider: str) -> Any:
    provider = provider.lower()
    if provider not in PROVIDERS:
        raise ValueError(f"Unsupported LLM provider: {provider}. Choose from {PROVIDERS}")
    
    if provider == 'openai':
        api_key = os.getenv('OPENAI_API_KEY')
        if not api_key:
            raise ValueError("OPENAI_API_KEY not set in .env")
        client = openai.OpenAI(api_key=api_key)
        return client, 'gpt-4o-mini'
    
    elif provider == 'groq':
        api_key = os.getenv('GROQ_API_KEY')
        if not api_key:
            raise ValueError("GROQ_API_KEY not set in .env")
        http_client = httpx.Client(transport=httpx.HTTPTransport(retries=0))
        client = openai.OpenAI(base_url="https://api.groq.com/openai/v1", api_key=api_key, http_client=http_client)
        return client, 'llama-3.3-70b-versatile'
    
    elif provider == 'gemini':
        api_key = os.getenv('GEMINI_API_KEY')
        if not api_key:
            raise ValueError("GEMINI_API_KEY not set in .env")
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel('gemini-1.5-pro')
        return model, None  # model used directly
    
    elif provider == 'ollama':
        base_url = os.getenv('OLLAMA_BASE_URL', 'http://localhost:11434/v1')
        http_client = httpx.Client(base_url=base_url)
        client = openai.OpenAI(base_url=base_url, api_key='ollama', http_client=http_client)
        return client, os.getenv('OLLAMA_MODEL', 'llama3.2')

def generate_structured_ticket(prompt: str) -> str:
    """
    Generate structured ticket JSON from prompt using configured LLM.
    
    Returns raw model response string. Caller handles JSON parsing.
    """
    provider = os.getenv('LLM_PROVIDER', 'openai')
    client, model_name = get_llm_client(provider)
    
    if provider == 'openai':
        response = client.chat.completions.create(
            model=model_name,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
            max_completion_tokens=2000
        )
        return response.choices[0].message.content.strip()

    elif provider == 'groq':
        response = client.chat.completions.create(
            model=model_name,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
            max_completion_tokens=2000
        )
        return response.choices[0].message.content.strip()

    elif provider == 'gemini':
        response = client.generate_content(prompt, generation_config=genai.types.GenerationConfig(
            temperature=0.1,
            max_output_tokens=2000
        ))
        return response.text.strip()
    
    elif provider == 'ollama':
        response = client.chat.completions.create(
            model=model_name,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
            max_completion_tokens=2000
        )
        return response.choices[0].message.content.strip()
    
    raise ValueError("Unhandled provider")


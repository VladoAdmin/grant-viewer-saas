"""
LLM client for GrantBot V2
Supports multiple providers: OpenRouter, OpenAI, Anthropic
"""
import json
import os
from typing import Any, Dict, List, Optional, Type, TypeVar

import requests
from pydantic import BaseModel

T = TypeVar('T', bound=BaseModel)


class LLMClient:
    """Generic LLM client with structured output support.
    
    Supports: ollama (default, local), openrouter, openai, anthropic
    """
    
    def __init__(
        self,
        provider: Optional[str] = None,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        temperature: float = 0.1
    ):
        self.provider = provider or os.getenv('LLM_PROVIDER', 'ollama')
        self.api_key = api_key or self._get_api_key()
        self.model = model or self._get_default_model()
        self.temperature = temperature
        self.base_url = self._get_base_url()
    
    def _get_api_key(self) -> str:
        """Get API key from environment"""
        if self.provider == 'ollama':
            return 'ollama'  # No API key needed for local Ollama
        elif self.provider == 'openrouter':
            return os.getenv('OPENROUTER_API_KEY', os.getenv('OPENROUTER_KEY', ''))
        elif self.provider == 'openai':
            return os.getenv('OPENAI_API_KEY', '')
        elif self.provider == 'anthropic':
            return os.getenv('ANTHROPIC_API_KEY', '')
        return ''
    
    def _get_default_model(self) -> str:
        """Get default model for provider"""
        if self.provider == 'ollama':
            return 'llama3.2:3b'
        elif self.provider == 'openrouter':
            return 'openai/gpt-4o-mini'
        elif self.provider == 'openai':
            return 'gpt-4o-mini'
        elif self.provider == 'anthropic':
            return 'claude-3-5-haiku-20241022'
        return 'gpt-4o-mini'
    
    def _get_base_url(self) -> str:
        """Get API base URL"""
        if self.provider == 'ollama':
            return os.getenv('OLLAMA_BASE_URL', 'http://127.0.0.1:11434') + '/v1'
        elif self.provider == 'openrouter':
            return 'https://openrouter.ai/api/v1'
        elif self.provider == 'openai':
            return 'https://api.openai.com/v1'
        elif self.provider == 'anthropic':
            return 'https://api.anthropic.com/v1'
        return 'https://openrouter.ai/api/v1'
    
    def _get_headers(self) -> Dict[str, str]:
        """Get HTTP headers for API calls"""
        headers = {
            'Content-Type': 'application/json',
        }
        
        if self.provider != 'ollama':
            headers['Authorization'] = f'Bearer {self.api_key}'
        
        if self.provider == 'openrouter':
            headers['HTTP-Referer'] = 'https://grantbot.local'
            headers['X-Title'] = 'GrantBot V2'
        
        return headers
    
    def complete(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        max_tokens: int = 2000
    ) -> str:
        """Simple completion without structured output"""
        messages = []
        if system_prompt:
            messages.append({'role': 'system', 'content': system_prompt})
        messages.append({'role': 'user', 'content': prompt})
        
        payload = {
            'model': self.model,
            'messages': messages,
            'temperature': self.temperature,
            'max_tokens': max_tokens
        }
        
        response = requests.post(
            f'{self.base_url}/chat/completions',
            headers=self._get_headers(),
            json=payload,
            timeout=60
        )
        response.raise_for_status()
        
        data = response.json()
        if not isinstance(data, dict) or 'choices' not in data or not data.get('choices'):
            raise ValueError(f"Unexpected LLM response: {str(data)[:400]}")
        return data['choices'][0]['message']['content']
    
    def complete_structured(
        self,
        prompt: str,
        output_schema: Type[T],
        system_prompt: Optional[str] = None,
        max_tokens: int = 2000
    ) -> T:
        """Completion with structured JSON output"""
        # Get schema from Pydantic model
        schema = output_schema.model_json_schema()
        
        # Build system prompt with schema
        structured_system = system_prompt or "You are a helpful assistant."
        structured_system += f"\n\nRespond with a JSON object matching this schema:\n{json.dumps(schema, indent=2)}"
        structured_system += "\n\nRespond ONLY with valid JSON. No markdown, no explanations outside the JSON."
        
        messages = [
            {'role': 'system', 'content': structured_system},
            {'role': 'user', 'content': prompt}
        ]
        
        payload = {
            'model': self.model,
            'messages': messages,
            'temperature': self.temperature,
            'max_tokens': max_tokens,
            'response_format': {'type': 'json_object'} if 'gpt' in self.model else None
        }
        
        # Remove None values
        payload = {k: v for k, v in payload.items() if v is not None}
        
        response = requests.post(
            f'{self.base_url}/chat/completions',
            headers=self._get_headers(),
            json=payload,
            timeout=120
        )
        response.raise_for_status()
        
        data = response.json()
        if not isinstance(data, dict) or 'choices' not in data or not data.get('choices'):
            raise ValueError(f"Unexpected LLM response: {str(data)[:400]}")
        content = data['choices'][0]['message']['content']
        
        # Parse JSON response
        try:
            parsed = json.loads(content)
            return output_schema.model_validate(parsed)
        except json.JSONDecodeError as e:
            raise ValueError(f"Failed to parse LLM response as JSON: {content[:200]}...") from e
    
    def classify_grant_link(
        self,
        url: str,
        title: Optional[str] = None,
        anchor_text: Optional[str] = None,
        surrounding_text: Optional[str] = None
    ) -> 'LLMClassificationResult':
        """Classify if a link is a grant call"""
        from .models import LLMClassificationResult
        
        prompt = f"""Analyze this link and determine if it points to a grant call (výzva) page.

URL: {url}
Title: {title or 'N/A'}
Anchor text: {anchor_text or 'N/A'}
Context: {surrounding_text[:500] if surrounding_text else 'N/A'}

Determine:
1. Is this a grant call page (výzva na podanie žiadosti/dotácie/grant)?
2. What is the status of the call?
   - open: Currently accepting applications
   - planned: Announced but not yet open
   - closed: Deadline has passed
   - unknown: Cannot determine from available info
3. Your confidence level (0-1)
4. Brief reasoning

Respond with valid JSON only."""
        
        return self.complete_structured(
            prompt=prompt,
            output_schema=LLMClassificationResult,
            system_prompt="You are a grant program analyzer. You identify grant calls and their status."
        )
    
    def extract_grant_details(
        self,
        html_content: str,
        url: str,
        title_hint: Optional[str] = None
    ) -> 'LLMExtractionResult':
        """Extract detailed grant information from HTML"""
        from .models import LLMExtractionResult
        
        # Truncate HTML if too long (LLM context limits)
        max_html = 15000  # ~4000 tokens
        if len(html_content) > max_html:
            html_content = html_content[:max_html] + "... [truncated]"
        
        prompt = f"""Extract detailed information about this grant call from the HTML content.

IMPORTANT: Specifically extract the field "oprávnení žiadatelia" / "eligible applicants" if present.
If it appears as a label-value pair, table row, or section header, capture it in eligible_applicants_text and also parse a clean list into eligible_applicants.

URL: {url}
Title hint: {title_hint or 'N/A'}

HTML Content:
```html
{html_content}
```

Extract all available information about this grant call. For dates, use ISO format (YYYY-MM-DD).
For monetary amounts, use numbers only (no currency symbols).

If information is not available, use null or empty arrays as appropriate."""
        
        return self.complete_structured(
            prompt=prompt,
            output_schema=LLMExtractionResult,
            system_prompt="You are a grant data extraction specialist. Extract structured information from grant call pages. Always respond with valid JSON.",
            max_tokens=4000
        )


# Singleton instance for reuse
_llm_client: Optional[LLMClient] = None


def get_llm_client() -> LLMClient:
    """Get or create singleton LLM client"""
    global _llm_client
    if _llm_client is None:
        _llm_client = LLMClient()
    return _llm_client


def reset_llm_client():
    """Reset singleton (useful for testing)"""
    global _llm_client
    _llm_client = None

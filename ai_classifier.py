#!/usr/bin/env python3
"""AI-powered document classifier for uncertain cases.

Uses cheap LLM (GPT-4o-mini) to classify documents when filename patterns fail.
Falls back to local Ollama if API unavailable.
"""

import os
import json
import re
from typing import Optional, Tuple
from dataclasses import dataclass
import requests


@dataclass
class AIClassification:
    doc_type: str  # 'key', 'form', 'technical', 'unknown'
    confidence: float
    reasoning: str
    should_chunk: bool


class AIClassifier:
    """AI-powered document classifier using cheap LLM."""
    
    # Cheap model options (in order of preference)
    PRIMARY_MODEL = "gpt-4o-mini"  # OpenAI - cheapest and fastest
    FALLBACK_MODEL = "llama3.2:3b"  # Local Ollama - free but slower
    
    def __init__(self):
        self.openai_key = os.environ.get("OPENAI_API_KEY")
        self.ollama_url = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434")
        self.use_openai = bool(self.openai_key)
    
    def _build_prompt(self, text: str, filename: str) -> str:
        """Build classification prompt."""
        text_preview = text[:2500] if len(text) > 2500 else text
        
        return f"""Analyze this document and classify it.

Filename: {filename}

Document text (first part):
---
{text_preview}
---

Categories:
1. KEY - Grant conditions, criteria, eligible costs, call description, evaluation methodology, guide for applicants. These should be EMBEDDED for search.
2. FORM - Application forms, templates to fill out, submission checklists. These should NOT be embedded (they're for filling out, not searching).
3. TECHNICAL - User manuals, GDPR info, technical specifications, portal instructions. These should NOT be embedded.
4. UNKNOWN - Cannot determine from text. Default to NOT embedding.

Respond ONLY in JSON:
{{
  "category": "key|form|technical|unknown",
  "confidence": 0.0-1.0,
  "reasoning": "brief explanation",
  "should_embed": true|false
}}

EMBEDDING RULES (critical):
- KEY documents (about grant content) → should_embed: true
- FORM documents (forms to fill) → should_embed: false
- TECHNICAL documents (manuals, GDPR) → should_embed: false
- UNKNOWN → should_embed: false (conservative)

Return only JSON, no other text."""

    def _call_openai(self, prompt: str) -> Optional[AIClassification]:
        """Call OpenAI API for classification."""
        if not self.openai_key:
            return None
        
        try:
            response = requests.post(
                "https://api.openai.com/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.openai_key}",
                    "Content-Type": "application/json"
                },
                json={
                    "model": self.PRIMARY_MODEL,
                    "messages": [
                        {"role": "system", "content": "You are a document classifier for grant management systems. Be concise and accurate."},
                        {"role": "user", "content": prompt}
                    ],
                    "temperature": 0.1,  # Low temp for consistency
                    "max_tokens": 150,
                    "response_format": {"type": "json_object"}
                },
                timeout=15
            )
            response.raise_for_status()
            
            result = response.json()
            content = result["choices"][0]["message"]["content"]
            data = json.loads(content)
            
            return AIClassification(
                doc_type=data.get("category", "unknown").lower(),
                confidence=data.get("confidence", 0.5),
                reasoning=data.get("reasoning", "No reasoning provided"),
                should_chunk=data.get("should_embed", True)
            )
            
        except Exception as e:
            print(f"OpenAI classification failed: {e}")
            return None

    def _call_ollama(self, prompt: str) -> Optional[AIClassification]:
        """Call local Ollama as fallback."""
        try:
            response = requests.post(
                f"{self.ollama_url}/api/generate",
                json={
                    "model": self.FALLBACK_MODEL,
                    "prompt": prompt,
                    "stream": False,
                    "options": {"temperature": 0.1}
                },
                timeout=30
            )
            response.raise_for_status()
            
            result = response.json()
            content = result.get("response", "")
            
            # Extract JSON from response
            json_match = re.search(r'\{[^}]+\}', content)
            if json_match:
                data = json.loads(json_match.group())
                return AIClassification(
                    doc_type=data.get("category", "unknown").lower(),
                    confidence=data.get("confidence", 0.5),
                    reasoning=data.get("reasoning", "Ollama classification"),
                    should_chunk=data.get("should_embed", True)
                )
            
            return None
            
        except Exception as e:
            print(f"Ollama classification failed: {e}")
            return None

    def classify(self, text: str, filename: str) -> Optional[AIClassification]:
        """
        Classify document using AI.
        
        Tries OpenAI first (fast, cheap), falls back to Ollama.
        """
        prompt = self._build_prompt(text, filename)
        
        # Try OpenAI first
        if self.use_openai:
            result = self._call_openai(prompt)
            if result:
                return result
        
        # Fallback to Ollama
        return self._call_ollama(prompt)
    
    def estimate_cost(self, text_length: int) -> dict:
        """Estimate classification cost."""
        # GPT-4o-mini pricing: $0.15 per 1M input tokens, $0.60 per 1M output tokens
        # Rough estimate: 2500 chars ≈ 625 tokens input, 100 tokens output
        input_tokens = min(text_length, 2500) / 4  # rough chars to tokens
        output_tokens = 100
        
        input_cost = (input_tokens / 1_000_000) * 0.15
        output_cost = (output_tokens / 1_000_000) * 0.60
        total_cost = input_cost + output_cost
        
        return {
            "input_tokens": int(input_tokens),
            "output_tokens": output_tokens,
            "estimated_cost_usd": total_cost,
            "cost_per_1000_classifications": total_cost * 1000
        }


def test_ai_classifier():
    """Test AI classifier with sample documents."""
    from document_classifier import DocumentClassifier
    
    # Sample texts
    samples = [
        ("Príloha č. 1 - Formulár ŽoNFP", "Formulár žiadosti o nenávratný finančný príspevok. Žiadateľ vyplní: názov projektu, IČO, adresa, ...", False),
        ("Metodika hodnotenia", "Hodnotiace kritériá pre výber projektov. Projekty sa hodnotia podľa: relevancie, kvality, udržateľnosti...", True),
        ("User manual", "Vitajte v portáli. Pre prihlásenie zadajte email a heslo. Kliknite na tlačidlo Prihlásiť...", False),
    ]
    
    ai = AIClassifier()
    rule_based = DocumentClassifier()
    
    print("="*70)
    print("AI CLASSIFIER TEST")
    print("="*70)
    
    for filename, text, expected in samples:
        print(f"\nFilename: {filename}")
        print(f"Expected: {'CHUNK' if expected else 'SKIP'}")
        
        # Rule-based first
        rule_result = rule_based.classify(filename, text)
        print(f"Rule-based: {rule_result.doc_type.value} (conf: {rule_result.confidence:.2f}) -> {'CHUNK' if rule_result.should_chunk else 'SKIP'}")
        
        # AI classification
        ai_result = ai.classify(text, filename)
        if ai_result:
            print(f"AI: {ai_result.doc_type} (conf: {ai_result.confidence:.2f}) -> {'CHUNK' if ai_result.should_chunk else 'SKIP'}")
            print(f"  Reasoning: {ai_result.reasoning}")
        else:
            print("AI: Failed")
    
    # Cost estimate
    print("\n" + "="*70)
    print("COST ESTIMATE")
    print("="*70)
    cost = ai.estimate_cost(2500)
    print(f"Per classification: ${cost['estimated_cost_usd']:.6f}")
    print(f"Per 1000 docs: ${cost['cost_per_1000_classifications']:.4f}")
    print(f"For 1000 UUID-classified docs: ~${cost['cost_per_1000_classifications']:.2f}")


if __name__ == "__main__":
    test_ai_classifier()

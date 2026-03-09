"""Query module for GrantBot.

Provides semantic search in calls + legislation.
"""

import json
import os
from typing import Dict, List, Optional

import requests

from storage import SUPABASE_URL, SUPABASE_KEY

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
EMBEDDING_MODEL = "text-embedding-3-small"


# ---------------------------------------------------------------------
# Supabase helpers
# ---------------------------------------------------------------------

def _sb_headers() -> Dict[str, str]:
    if not SUPABASE_URL or not SUPABASE_KEY:
        raise RuntimeError("SUPABASE_URL/KEY missing")
    return {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "return=representation",
    }


def _sb_get(table: str, params: Dict) -> List[Dict]:
    url = f"{SUPABASE_URL}/rest/v1/{table}"
    resp = requests.get(url, headers=_sb_headers(), params=params)
    resp.raise_for_status()
    return resp.json() if resp.text else []


# ---------------------------------------------------------------------
# Embeddings + vector helpers
# ---------------------------------------------------------------------

def embed_query(text: str) -> List[float]:
    if not OPENAI_API_KEY:
        raise RuntimeError("OPENAI_API_KEY missing for embeddings")
    resp = requests.post(
        "https://api.openai.com/v1/embeddings",
        headers={
            "Authorization": f"Bearer {OPENAI_API_KEY}",
            "Content-Type": "application/json",
        },
        json={"model": EMBEDDING_MODEL, "input": text},
        timeout=60,
    )
    resp.raise_for_status()
    data = resp.json()
    return data["data"][0]["embedding"]


def _vector_literal(vec: List[float]) -> str:
    return "[" + ",".join(f"{x:.6f}" for x in vec) + "]"


# ---------------------------------------------------------------------
# Search APIs
# ---------------------------------------------------------------------

def search_calls(query: str, filters: Optional[Dict] = None, limit: int = 10) -> List[Dict]:
    vec = embed_query(query)
    vec_lit = _vector_literal(vec)

    params = {
        "select": "call_id,chunk_text,source_type,source_url,score:embedding<->'" + vec_lit + "'",
        "order": "embedding<->'" + vec_lit + "'",
        "limit": str(limit),
    }
    if filters:
        for k, v in filters.items():
            params[k] = f"eq.{v}"

    return _sb_get("v2_call_chunks", params)


def search_legislation(query: str, limit: int = 10) -> List[Dict]:
    vec = embed_query(query)
    vec_lit = _vector_literal(vec)

    params = {
        "select": "document_id,chunk_text,score:embedding<->'" + vec_lit + "'",
        "order": "embedding<->'" + vec_lit + "'",
        "limit": str(limit),
    }
    return _sb_get("legislation_chunks", params)


def match_call_to_legislation(call_id: str, limit: int = 5) -> List[Dict]:
    # Use summary or top chunks as query
    rows = _sb_get(
        "v2_enriched_calls",
        {"select": "summary_text,description,title_clean", "id": f"eq.{call_id}"},
    )
    if rows:
        text = (rows[0].get("summary_text") or rows[0].get("description") or "")
        title = rows[0].get("title_clean") or ""
        query = (title + " " + text).strip()
    else:
        query = ""

    if not query:
        chunks = _sb_get(
            "v2_call_chunks",
            {"select": "chunk_text", "call_id": f"eq.{call_id}", "limit": "3"},
        )
        query = " ".join([c["chunk_text"] for c in chunks])

    if not query:
        return []

    return search_legislation(query, limit=limit)


def answer_user_query(user_question: str) -> Dict:
    """Entry point: return top call + legislation matches for a user query."""
    calls = search_calls(user_question, limit=5)
    legislation = search_legislation(user_question, limit=5)

    return {
        "question": user_question,
        "top_calls": calls,
        "top_legislation": legislation,
    }


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="GrantBot semantic search")
    parser.add_argument("query")
    args = parser.parse_args()

    print(json.dumps(answer_user_query(args.query), indent=2))

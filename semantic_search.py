#!/usr/bin/env python3
"""Semantic search for grant calls using vector similarity.

Usage:
    python3 v2/semantic_search.py "voda"
    python3 v2/semantic_search.py "inovácie" --limit 5
"""

import json
import os
import sys
from typing import Dict, List, Optional

import numpy as np
import requests

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from storage import SUPABASE_URL, SUPABASE_KEY

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
EMBEDDING_MODEL = "text-embedding-3-small"
ACTIVE_STATUSES = ("Otvorená", "Vyhlásená", "Plánovaná")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _sb_headers() -> Dict[str, str]:
    return {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
    }


def embed_query(text: str) -> np.ndarray:
    """Generate embedding for a query string via OpenAI."""
    if not OPENAI_API_KEY:
        raise RuntimeError("OPENAI_API_KEY missing")
    resp = requests.post(
        "https://api.openai.com/v1/embeddings",
        headers={"Authorization": f"Bearer {OPENAI_API_KEY}", "Content-Type": "application/json"},
        json={"model": EMBEDDING_MODEL, "input": text},
        timeout=30,
    )
    resp.raise_for_status()
    return np.array(resp.json()["data"][0]["embedding"], dtype=np.float32)


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """Cosine similarity between two vectors."""
    norm_a = np.linalg.norm(a)
    norm_b = np.linalg.norm(b)
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return float(np.dot(a, b) / (norm_a * norm_b))


def _parse_embedding(emb_str: str) -> np.ndarray:
    """Parse embedding string from Supabase (e.g. '[-0.001,0.068,...]')."""
    return np.array(json.loads(emb_str), dtype=np.float32)


# ---------------------------------------------------------------------------
# Data fetching
# ---------------------------------------------------------------------------

def fetch_all_chunks() -> List[Dict]:
    """Fetch all call chunks with embeddings from Supabase."""
    resp = requests.get(
        f"{SUPABASE_URL}/rest/v1/v2_call_chunks",
        headers=_sb_headers(),
        params={"select": "id,call_id,chunk_text,source_type,embedding", "limit": "1000"},
    )
    resp.raise_for_status()
    return resp.json()


def fetch_call_metadata(call_ids: List[str]) -> Dict[str, Dict]:
    """Fetch grant_calls_v2 metadata for given call IDs."""
    if not call_ids:
        return {}
    # Supabase IN filter
    ids_filter = f"in.({','.join(call_ids)})"
    resp = requests.get(
        f"{SUPABASE_URL}/rest/v1/grant_calls_v2",
        headers=_sb_headers(),
        params={
            "select": "id,title,status,deadline_at,provider,total_allocation,call_url",
            "id": ids_filter,
        },
    )
    resp.raise_for_status()
    return {r["id"]: r for r in resp.json()}


# ---------------------------------------------------------------------------
# Main search
# ---------------------------------------------------------------------------

def semantic_search_calls(query: str, limit: int = 10, statuses: Optional[tuple] = ACTIVE_STATUSES) -> List[Dict]:
    """Search grant calls by semantic similarity.

    Args:
        query: Search query (e.g. "voda", "inovácie", "energetika")
        limit: Max number of unique calls to return

    Returns:
        List of call dicts sorted by relevance (highest similarity first),
        each containing: call_id, title, status, deadline_at, provider,
        total_allocation, call_url, similarity, snippet
    """
    # 1. Generate query embedding
    query_vec = embed_query(query)

    # 2. Fetch all chunks (small dataset ~50 chunks)
    chunks = fetch_all_chunks()

    # 3. Compute similarity for each chunk
    scored = []
    for chunk in chunks:
        if not chunk.get("embedding"):
            continue
        emb = _parse_embedding(chunk["embedding"])
        sim = cosine_similarity(query_vec, emb)
        scored.append({
            "call_id": chunk["call_id"],
            "chunk_text": chunk["chunk_text"],
            "source_type": chunk.get("source_type"),
            "similarity": sim,
        })

    # 4. Sort by similarity (descending)
    scored.sort(key=lambda x: x["similarity"], reverse=True)

    # 5. Deduplicate by call_id (keep best chunk per call)
    seen = {}
    for item in scored:
        cid = item["call_id"]
        if cid not in seen:
            seen[cid] = item

    # 6. Fetch metadata for unique calls
    unique_ids = list(seen.keys())
    metadata = fetch_call_metadata(unique_ids)

    # 7. Build results, filter by active status
    results = []
    for cid, chunk_info in seen.items():
        meta = metadata.get(cid, {})
        status = meta.get("status", "")
        if statuses and status not in statuses:
            continue

        snippet = chunk_info["chunk_text"]
        if len(snippet) > 200:
            snippet = snippet[:200] + "…"

        results.append({
            "call_id": cid,
            "title": meta.get("title", "N/A"),
            "status": status,
            "deadline_at": meta.get("deadline_at"),
            "provider": meta.get("provider"),
            "total_allocation": meta.get("total_allocation"),
            "call_url": meta.get("call_url"),
            "similarity": chunk_info["similarity"],
            "snippet": snippet,
        })

    # Sort by similarity and limit
    results.sort(key=lambda x: x["similarity"], reverse=True)
    return results[:limit]


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def print_results(query: str, results: List[Dict]):
    """Pretty-print search results."""
    print(f"\n🔍 Sémantické vyhľadávanie: \"{query}\"")
    print(f"   Nájdených výziev: {len(results)}")
    print("=" * 80)

    for i, r in enumerate(results, 1):
        sim_pct = r["similarity"] * 100
        deadline = r["deadline_at"][:10] if r["deadline_at"] else "N/A"
        alloc = f"{r['total_allocation']:,.0f} €" if r["total_allocation"] else "N/A"

        print(f"\n{i}. [{sim_pct:.1f}%] {r['title']}")
        print(f"   Status: {r['status']} | Deadline: {deadline} | Provider: {r['provider']}")
        print(f"   Alokácia: {alloc}")
        print(f"   Snippet: {r['snippet']}")
        if r.get("call_url"):
            print(f"   URL: {r['call_url']}")


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Semantic search for grant calls")
    parser.add_argument("query", help="Search query")
    parser.add_argument("--limit", type=int, default=10, help="Max results")
    parser.add_argument("--all", action="store_true", help="Include all statuses (not just active)")
    args = parser.parse_args()

    statuses = None if args.all else ACTIVE_STATUSES
    results = semantic_search_calls(args.query, limit=args.limit, statuses=statuses)
    print_results(args.query, results)


if __name__ == "__main__":
    main()

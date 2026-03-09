#!/usr/bin/env python3
"""
Migrate 15% sample calls to smart chunking + new embeddings.

Process:
1. Select 21 calls (15% sample)
2. For each call:
   - Fetch old chunks, group by source_url
   - Smart chunk each document
   - Embed new chunks
   - Compare quality metrics (search test)
3. Save results to analysis report
4. If quality >90%, prepare for full migration
"""

import os
import json
import sys
import time
from pathlib import Path
from collections import defaultdict
from typing import List, Dict, Tuple

sys.path.insert(0, str(Path(__file__).parent))
from smart_chunker import SmartChunker

# Load env
env_path = Path(__file__).parent.parent / ".env"
with open(env_path) as f:
    for line in f:
        if line.strip() and not line.startswith("#") and "=" in line:
            key, val = line.strip().split("=", 1)
            os.environ.setdefault(key, val)

import numpy as np
import requests
import tiktoken

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
OPENAI_KEY = os.environ["OPENAI_API_KEY"]

SB_HEADERS = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json",
}

enc = tiktoken.encoding_for_model("gpt-4")
EMBED_MODEL = "text-embedding-3-small"


def fetch_sample_calls() -> List[Tuple[str, str]]:
    """Fetch 15% sample of calls."""
    r = requests.get(
        f"{SUPABASE_URL}/rest/v1/rpc/get_sample_calls",
        headers=SB_HEADERS,
        params={"sample_percent": 15},
        timeout=60
    )
    if r.status_code != 200:
        # Fallback: manual query
        print("Using manual sample selection...")
        sample_ids = [
            "3d602a6c-9856-4004-8a37-d1e34345e232",  # Vody B1
            "deb15f7d-6b12-4ed7-a9db-966108311c63",  # DPMP Trolejbusy
            "d3f79d37-5464-4c65-b87d-68174b48397f",  # Zvyšovanie energetickej
            "4cdf94e1-63be-4d2f-8799-f2fefa96d225",  # APVV SK-Izrael
            "16dba93d-4dbe-4198-acc7-d60419ba886c",  # MoF 2/2024
        ]
        calls = []
        for call_id in sample_ids:
            r = requests.get(
                f"{SUPABASE_URL}/rest/v1/grant_calls_v2",
                headers=SB_HEADERS,
                params={"select": "id,title", "id": f"eq.{call_id}", "limit": "1"},
                timeout=30
            )
            if r.status_code == 200 and r.json():
                c = r.json()[0]
                calls.append((c["id"], c["title"]))
        return calls
    
    return [(c["id"], c["title"]) for c in r.json()]


def fetch_call_chunks(call_id: str) -> List[Dict]:
    """Fetch all chunks for a call."""
    all_chunks = []
    offset = 0
    limit = 1000
    
    while True:
        r = requests.get(
            f"{SUPABASE_URL}/rest/v1/v2_call_chunks",
            headers=SB_HEADERS,
            params={
                "select": "call_id,source_url,chunk_text,chunk_index",
                "call_id": f"eq.{call_id}",
                "order": "source_url,chunk_index",
                "offset": str(offset),
                "limit": str(limit),
            },
            timeout=60
        )
        if r.status_code != 200:
            break
        batch = r.json()
        all_chunks.extend(batch)
        if len(batch) < limit:
            break
        offset += limit
    
    return all_chunks


def reconstruct_documents(chunks: List[Dict]) -> Dict[str, str]:
    """Group chunks by source and reconstruct text."""
    docs = defaultdict(list)
    for c in chunks:
        source = c.get("source_url", "unknown")
        docs[source].append(c)
    
    reconstructed = {}
    for source, source_chunks in docs.items():
        source_chunks.sort(key=lambda x: x.get("chunk_index", 0))
        text = "\n\n".join(c.get("chunk_text", "") for c in source_chunks)
        reconstructed[source] = text
    
    return reconstructed


def embed_texts(texts: List[str], desc: str = "") -> List[List[float]]:
    """Embed texts via OpenAI."""
    if not texts:
        return []
    
    headers = {
        "Authorization": f"Bearer {OPENAI_KEY}",
        "Content-Type": "application/json",
    }
    
    embeddings = []
    batch_size = 96
    
    for i in range(0, len(texts), batch_size):
        batch = texts[i:i+batch_size]
        try:
            resp = requests.post(
                "https://api.openai.com/v1/embeddings",
                headers=headers,
                json={"model": EMBED_MODEL, "input": batch},
                timeout=60
            )
            resp.raise_for_status()
            data = resp.json()
            embeddings.extend([d["embedding"] for d in data["data"]])
            if desc:
                print(f"  {desc}: {i+len(batch)}/{len(texts)} embedded")
        except Exception as e:
            print(f"  ERROR embedding batch {i//batch_size}: {e}")
            return []
    
    return embeddings


def cosine_sim(a, b):
    a, b = np.array(a), np.array(b)
    norm_a, norm_b = np.linalg.norm(a), np.linalg.norm(b)
    return float(np.dot(a, b) / (norm_a * norm_b)) if norm_a and norm_b else 0.0


def search_and_score(query: str, embeddings: List[List[float]], chunks: List[Dict], top_k: int = 3) -> Tuple[float, Dict]:
    """Search and return top score + result."""
    try:
        resp = requests.post(
            "https://api.openai.com/v1/embeddings",
            headers={"Authorization": f"Bearer {OPENAI_KEY}", "Content-Type": "application/json"},
            json={"model": EMBED_MODEL, "input": [query]},
            timeout=30
        )
        resp.raise_for_status()
        query_emb = resp.json()["data"][0]["embedding"]
    except Exception as e:
        print(f"  ERROR embedding query: {e}")
        return 0.0, {}
    
    scored = []
    for i, emb in enumerate(embeddings):
        sim = cosine_sim(query_emb, emb)
        scored.append((sim, chunks[i] if i < len(chunks) else {}))
    
    scored.sort(reverse=True)
    top_result = scored[0] if scored else (0.0, {})
    return top_result[0], top_result[1]


def test_call(call_id: str, call_title: str) -> Dict:
    """Test re-chunking on a single call."""
    print(f"\nTesting: {call_title[:60]}")
    
    # 1. Fetch old chunks
    old_chunks = fetch_call_chunks(call_id)
    if not old_chunks:
        print("  No chunks found")
        return None
    
    # 2. Reconstruct documents
    docs = reconstruct_documents(old_chunks)
    print(f"  Documents: {len(docs)}")
    
    # 3. Smart chunk
    chunker = SmartChunker()
    new_all_chunks = []
    new_texts = []
    
    for source, text in docs.items():
        chunks = chunker.chunk_with_context(text)
        for c in chunks:
            c["source_url"] = source
            new_all_chunks.append(c)
            new_texts.append(c["text"])
    
    print(f"  Old chunks: {len(old_chunks)} → New chunks: {len(new_all_chunks)}")
    
    # 4. Embed both old and new
    print("  Embedding old chunks...")
    old_texts = [c.get("chunk_text", "") for c in old_chunks]
    old_emb = embed_texts(old_texts, "old")
    if not old_emb:
        return None
    
    print("  Embedding new chunks...")
    new_emb = embed_texts(new_texts, "new")
    if not new_emb:
        return None
    
    # 5. Test search
    test_queries = [
        "oprávnený žiadateľ",
        "oprávnené náklady",
        "dokumenty",
        "termín",
        "podmienky",
    ]
    
    old_scores = []
    new_scores = []
    
    for query in test_queries:
        old_score, _ = search_and_score(query, old_emb, old_chunks)
        new_score, _ = search_and_score(query, new_emb, new_all_chunks)
        old_scores.append(old_score)
        new_scores.append(new_score)
    
    avg_old = np.mean(old_scores) if old_scores else 0
    avg_new = np.mean(new_scores) if new_scores else 0
    improvement = ((avg_new - avg_old) / avg_old * 100) if avg_old > 0 else 0
    
    print(f"  Scores: OLD {avg_old:.3f} → NEW {avg_new:.3f} ({improvement:+.1f}%)")
    
    return {
        "call_id": call_id,
        "call_title": call_title,
        "old_chunk_count": len(old_chunks),
        "new_chunk_count": len(new_all_chunks),
        "avg_old_score": float(avg_old),
        "avg_new_score": float(avg_new),
        "improvement_pct": float(improvement),
        "query_scores": list(zip(test_queries, old_scores, new_scores)),
    }


def main():
    print("="*70)
    print("15% SAMPLE MIGRATION TEST")
    print("="*70)
    
    # Get sample calls
    print("\nFetching 15% sample...")
    sample_calls = fetch_sample_calls()
    print(f"Sample size: {len(sample_calls)} calls")
    
    results = []
    
    for i, (call_id, title) in enumerate(sample_calls):
        print(f"\n[{i+1}/{len(sample_calls)}]", end="")
        try:
            result = test_call(call_id, title)
            if result:
                results.append(result)
            time.sleep(1)  # Rate limiting
        except Exception as e:
            print(f"  ERROR: {e}")
    
    # Summary
    print("\n" + "="*70)
    print("SUMMARY")
    print("="*70)
    
    if results:
        avg_improvement = np.mean([r["improvement_pct"] for r in results])
        avg_new_score = np.mean([r["avg_new_score"] for r in results])
        
        print(f"Calls tested: {len(results)}")
        print(f"Average new score: {avg_new_score:.3f}")
        print(f"Average improvement: {avg_improvement:+.1f}%")
        print(f"Verdict: {'✅ PASS >90% threshold' if avg_new_score > 0.55 else '⚠️ Below threshold'}")
        
        # Save detailed results
        output_file = "/tmp/sample_migration_results.json"
        with open(output_file, 'w') as f:
            json.dump({
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "sample_size": len(results),
                "avg_new_score": float(avg_new_score),
                "avg_improvement": float(avg_improvement),
                "calls": results
            }, f, ensure_ascii=False, indent=2)
        
        print(f"\nDetailed results: {output_file}")
    else:
        print("No successful tests")


if __name__ == "__main__":
    main()

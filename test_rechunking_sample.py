#!/usr/bin/env python3
"""Test re-chunking on 15% sample of calls.

Process:
1. Fetch existing chunks from v2_call_chunks
2. Group by source_url (reconstruct document text)
3. Apply smart chunking
4. Generate new embeddings
5. Test search quality vs old chunks
"""

import os
import sys
import json
import re
from pathlib import Path
from typing import List, Dict, Tuple
from collections import defaultdict

sys.path.insert(0, str(Path(__file__).parent))
from smart_chunker import SmartChunker

# Load env
env_path = Path(__file__).parent.parent / ".env"
if env_path.exists():
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

enc = tiktoken.encoding_for_model("gpt-4")
EMBED_MODEL = "text-embedding-3-small"

SB_HEADERS = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json",
}


def fetch_chunks_for_call(call_id: str) -> List[Dict]:
    """Fetch all chunks for a call from Supabase."""
    all_chunks = []
    offset = 0
    limit = 1000
    
    while True:
        params = {
            "select": "id,call_id,source_url,chunk_text,chunk_index,token_count",
            "call_id": f"eq.{call_id}",
            "order": "source_url,chunk_index",
            "offset": str(offset),
            "limit": str(limit),
        }
        r = requests.get(
            f"{SUPABASE_URL}/rest/v1/v2_call_chunks",
            headers=SB_HEADERS,
            params=params,
            timeout=60
        )
        r.raise_for_status()
        batch = r.json()
        all_chunks.extend(batch)
        if len(batch) < limit:
            break
        offset += limit
    
    return all_chunks


def reconstruct_documents(chunks: List[Dict]) -> Dict[str, str]:
    """Group chunks by source_url and reconstruct full text."""
    docs = defaultdict(list)
    for chunk in chunks:
        source = chunk.get("source_url", "unknown")
        docs[source].append(chunk)
    
    reconstructed = {}
    for source, source_chunks in docs.items():
        # Sort by chunk_index
        source_chunks.sort(key=lambda x: x.get("chunk_index", 0))
        # Join text with newlines
        full_text = "\n\n".join(c.get("chunk_text", "") for c in source_chunks)
        reconstructed[source] = full_text
    
    return reconstructed


def embed_texts(texts: List[str]) -> List[List[float]]:
    """Get embeddings from OpenAI."""
    if not texts:
        return []
    
    headers = {
        "Authorization": f"Bearer {OPENAI_KEY}",
        "Content-Type": "application/json",
    }
    
    all_embeddings = []
    batch_size = 96
    
    for i in range(0, len(texts), batch_size):
        batch = texts[i:i+batch_size]
        resp = requests.post(
            "https://api.openai.com/v1/embeddings",
            headers=headers,
            json={"model": EMBED_MODEL, "input": batch},
            timeout=60
        )
        resp.raise_for_status()
        data = resp.json()
        all_embeddings.extend([d["embedding"] for d in data["data"]])
    
    return all_embeddings


def cosine_similarity(a, b):
    a, b = np.array(a), np.array(b)
    norm_a, norm_b = np.linalg.norm(a), np.linalg.norm(b)
    return float(np.dot(a, b) / (norm_a * norm_b)) if norm_a and norm_b else 0.0


def search_chunks(query: str, chunks: List[Dict], embeddings: List[List[float]], top_k: int = 5):
    """Semantic search over chunks."""
    query_emb = embed_texts([query])[0]
    
    scored = []
    for i, emb in enumerate(embeddings):
        sim = cosine_similarity(query_emb, emb)
        scored.append((i, sim, chunks[i]))
    
    scored.sort(key=lambda x: x[1], reverse=True)
    return scored[:top_k]


def test_call(call_id: str, call_title: str, test_queries: List[str]):
    """Test re-chunking on a single call."""
    print(f"\n{'='*70}")
    print(f"TESTING: {call_title[:60]}")
    print(f"Call ID: {call_id}")
    print(f"{'='*70}")
    
    # 1. Fetch existing chunks
    print("\n1. Fetching existing chunks...")
    old_chunks = fetch_chunks_for_call(call_id)
    print(f"   Found {len(old_chunks)} old chunks")
    
    if not old_chunks:
        print("   No chunks found, skipping")
        return None
    
    # 2. Reconstruct documents
    print("\n2. Reconstructing documents...")
    docs = reconstruct_documents(old_chunks)
    print(f"   Reconstructed {len(docs)} documents")
    for source, text in list(docs.items())[:3]:
        print(f"   - {source[:60]}... ({len(text)} chars)")
    
    # 3. Smart chunking
    print("\n3. Applying smart chunking...")
    chunker = SmartChunker()
    new_all_chunks = []
    new_all_texts = []
    
    for source, text in docs.items():
        chunks = chunker.chunk_with_context(text)
        for c in chunks:
            # Add source metadata
            c["source_url"] = source
            c["call_id"] = call_id
            new_all_chunks.append(c)
            new_all_texts.append(c["text"])
    
    print(f"   Created {len(new_all_chunks)} new chunks")
    
    # Count by type
    type_counts = defaultdict(int)
    for c in new_all_chunks:
        type_counts[c["type"]] += 1
    print(f"   By type: {dict(type_counts)}")
    
    # 4. Embed new chunks
    print("\n4. Embedding new chunks...")
    new_embeddings = embed_texts(new_all_texts)
    print(f"   Embedded {len(new_embeddings)} chunks")
    
    # 5. Test search
    print("\n5. Testing search quality...")
    
    # Prepare old chunks for comparison
    old_texts = [c.get("chunk_text", "") for c in old_chunks]
    old_embeddings = embed_texts(old_texts)
    
    results = {
        "call_id": call_id,
        "call_title": call_title,
        "old_chunk_count": len(old_chunks),
        "new_chunk_count": len(new_all_chunks),
        "queries": []
    }
    
    for query in test_queries:
        print(f"\n   Query: '{query}'")
        
        # Search old chunks
        old_results = search_chunks(query, old_chunks, old_embeddings, top_k=3)
        print(f"   OLD top: {old_results[0][1]:.3f} | {old_results[0][2].get('chunk_text', '')[:80]}...")
        
        # Search new chunks
        new_results = search_chunks(query, new_all_chunks, new_embeddings, top_k=3)
        print(f"   NEW top: {new_results[0][1]:.3f} | {new_results[0][2].get('raw_text', '')[:80]}...")
        
        # Check if results are relevant (manual inspection needed)
        results["queries"].append({
            "query": query,
            "old_top_score": old_results[0][1],
            "new_top_score": new_results[0][1],
            "old_snippet": old_results[0][2].get("chunk_text", "")[:200],
            "new_snippet": new_results[0][2].get("raw_text", "")[:200],
            "new_section": " > ".join(new_results[0][2].get("section_path", [])[-2:]) if new_results[0][2].get("section_path") else ""
        })
    
    return results


def main():
    # Test queries relevant to grant applications
    test_queries = [
        "Kto je oprávnený žiadateľ?",
        "Aké náklady sú oprávnené?",
        "Aké dokumenty treba predložiť?",
        "Aký je termín na predloženie žiadosti?",
        "Aké sú podmienky pre schválenie?",
    ]
    
    # 15% sample call IDs (from previous query)
    sample_calls = [
        ("3d602a6c-9856-4004-8a37-d1e34345e232", "Vody – výzva č. B1 (2026)"),
        ("deb15f7d-6b12-4ed7-a9db-966108311c63", "DPMP Trolejbusy-2F a DPMK MUZ-2F"),
        ("d3f79d37-5464-4c65-b87d-68174b48397f", "Zvyšovanie energetickej účinnosti – L (2026)"),
    ]
    
    all_results = []
    
    for call_id, call_title in sample_calls:
        try:
            result = test_call(call_id, call_title, test_queries)
            if result:
                all_results.append(result)
        except Exception as e:
            print(f"ERROR testing {call_title}: {e}")
            import traceback
            traceback.print_exc()
    
    # Save results
    output_file = "/tmp/chunking_test_results.json"
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(all_results, f, ensure_ascii=False, indent=2)
    
    print(f"\n{'='*70}")
    print(f"SUMMARY")
    print(f"{'='*70}")
    print(f"Tested {len(all_results)} calls")
    print(f"Results saved to: {output_file}")
    
    for r in all_results:
        print(f"\n{r['call_title'][:50]}:")
        print(f"  Old chunks: {r['old_chunk_count']} → New: {r['new_chunk_count']}")
        for q in r['queries'][:2]:
            print(f"  '{q['query'][:30]}...': {q['old_top_score']:.3f} → {q['new_top_score']:.3f}")


if __name__ == "__main__":
    main()

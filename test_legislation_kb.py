"""Test script for legislation KB + semantic search.

Checks:
1) Tables exist
2) Document insert + read
3) Embeddings generated + stored
4) Search returns relevant results
"""

import json
import os
import sys
import uuid

import requests

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from storage import SUPABASE_URL, SUPABASE_KEY
from v2.grantbot_query import search_legislation
from v2.legislation_ingestion import embed_texts


def _sb_headers():
    return {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "return=representation",
    }


def _sb_get(table: str, params: dict):
    url = f"{SUPABASE_URL}/rest/v1/{table}"
    resp = requests.get(url, headers=_sb_headers(), params=params)
    resp.raise_for_status()
    return resp.json()


def _sb_post(table: str, data: list):
    url = f"{SUPABASE_URL}/rest/v1/{table}"
    resp = requests.post(url, headers=_sb_headers(), data=json.dumps(data))
    resp.raise_for_status()
    return resp.json()


def main():
    if not SUPABASE_URL or not SUPABASE_KEY:
        raise RuntimeError("SUPABASE_URL/KEY missing")

    # 1) Table existence (simple select)
    _sb_get("legislation_documents", {"limit": "1"})
    _sb_get("legislation_chunks", {"limit": "1"})

    # 2) Insert document + file
    doc_id = str(uuid.uuid4())
    file_id = str(uuid.uuid4())

    _sb_post(
        "legislation_documents",
        [
            {
                "id": doc_id,
                "title": "Test Legislation Doc",
                "doc_type": "test",
                "jurisdiction": "SK",
                "source_url": f"https://example.com/{doc_id}",
            }
        ],
    )

    _sb_post(
        "legislation_files",
        [
            {
                "id": file_id,
                "document_id": doc_id,
                "file_url": f"https://example.com/{doc_id}.pdf",
                "file_type": "pdf",
            }
        ],
    )

    # 3) Embeddings + chunks
    text = "Test legislation content about grant eligibility and funding rules."
    emb = embed_texts([text])[0]
    _sb_post(
        "legislation_chunks",
        [
            {
                "document_id": doc_id,
                "file_id": file_id,
                "chunk_index": 0,
                "chunk_text": text,
                "token_count": len(text.split()),
                "embedding": emb,
            }
        ],
    )

    # 4) Search
    results = search_legislation("grant eligibility funding", limit=5)
    hit = any(r.get("document_id") == doc_id for r in results)

    print(
        json.dumps(
            {
                "tables_ok": True,
                "doc_inserted": True,
                "embedding_saved": True,
                "search_hit": hit,
                "results": results[:3],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()

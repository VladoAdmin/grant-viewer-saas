"""Embedding generation and storage.

Reuses patterns from vectorize_calls_v3.py.
Uses OpenAI text-embedding-3-small (1536 dim) for cost efficiency.
"""

import json
import logging
import time
from typing import Dict, List, Optional

from openai import OpenAI

from ..config import EMBED_BATCH_SIZE, EMBED_DIM, EMBED_MODEL, OPENAI_API_KEY
from ..db import get_db
from .chunker import Chunk, chunk_document, count_tokens

log = logging.getLogger(__name__)

_oai = None


def _get_openai() -> OpenAI:
    global _oai
    if _oai is None:
        _oai = OpenAI(api_key=OPENAI_API_KEY, timeout=60.0)
    return _oai


def embed_texts(texts: List[str]) -> List[List[float]]:
    """Generate embeddings for a list of texts.

    Uses batching and exponential backoff for reliability.
    Returns list of embedding vectors (1536 dim).
    """
    if not texts:
        return []

    oai = _get_openai()
    embeddings: List[List[float]] = []

    for i in range(0, len(texts), EMBED_BATCH_SIZE):
        batch = texts[i:i + EMBED_BATCH_SIZE]

        for attempt in range(5):
            try:
                resp = oai.embeddings.create(model=EMBED_MODEL, input=batch)
                embeddings.extend([d.embedding for d in resp.data])
                break
            except Exception as e:
                wait = min(60, 2 ** (attempt + 1))
                log.warning(f"Embedding error (attempt {attempt + 1}/5): {e} (sleeping {wait}s)")
                time.sleep(wait)
                if attempt == 4:
                    log.error(f"Embedding failed after 5 attempts, using zero vectors")
                    embeddings.extend([[0.0] * EMBED_DIM for _ in batch])

    return embeddings


def embed_and_store(call_id: int, call_title: str,
                    documents: List[Dict], dry_run: bool = False) -> int:
    """Process documents: chunk, embed, and store in DB.

    Args:
        call_id: Grant call ID
        call_title: Grant call title (for context prefix)
        documents: List of dicts with keys: text, filename, doc_type, source_url
        dry_run: If True, skip embedding and DB writes

    Returns:
        Number of chunks created
    """
    db = get_db()
    all_chunks: List[Chunk] = []

    for doc in documents:
        text = doc.get("text", "")
        if not text or len(text) < 50:
            continue

        filename = doc.get("filename", "unknown")
        doc_type = doc.get("doc_type", "main")
        source_url = doc.get("source_url", "")

        chunks = chunk_document(text, call_title, filename, doc_type)
        for chunk in chunks:
            chunk.source_url = source_url  # type: ignore
        all_chunks.extend(chunks)

    if not all_chunks:
        log.info(f"No chunks generated for call {call_id}")
        return 0

    # Log cost estimate
    total_tokens = sum(c.token_count for c in all_chunks)
    cost_estimate = total_tokens / 1_000_000 * 0.02  # text-embedding-3-small pricing
    log.info(f"Call {call_id}: {len(all_chunks)} chunks, ~{total_tokens} tokens, "
             f"~${cost_estimate:.4f} estimated cost")

    if dry_run:
        log.info(f"DRY RUN: would embed {len(all_chunks)} chunks for call {call_id}")
        return len(all_chunks)

    # Delete existing chunks (idempotent re-embedding)
    db.delete_chunks_for_call(call_id)

    # Generate embeddings
    texts = [c.text for c in all_chunks]
    log.info(f"Embedding {len(texts)} chunks...")
    embeddings = embed_texts(texts)
    log.info(f"Embedding complete")

    # Build DB rows
    rows = []
    for chunk, emb in zip(all_chunks, embeddings):
        rows.append({
            "call_id": call_id,
            "content": chunk.text,
            "embedding": json.dumps(emb),
            "chunk_index": chunk.chunk_index,
            "source": getattr(chunk, "source_url", chunk.doc_name),
            "doc_type": chunk.doc_type,
        })

    # Insert to DB
    log.info(f"Inserting {len(rows)} chunks to DB...")
    db.insert_chunks(rows)
    log.info(f"Done: {len(rows)} chunks stored for call {call_id}")

    return len(rows)

"""Embedding generation and storage.

Reuses patterns from vectorize_calls_v3.py.
Uses OpenAI text-embedding-3-large (3072 dim).
Supports metadata enrichment via GPT-4o-mini.
"""

import json
import logging
import time
from typing import Dict, List, Optional

from openai import OpenAI

from ..config import EMBED_BATCH_SIZE, EMBED_DIM, EMBED_MODEL, OPENAI_API_KEY
from ..db import get_db
from .chunker import Chunk, chunk_document, count_tokens
from .metadata_generator import (
    build_enriched_prefix,
    generate_batch_metadata,
)

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
    Returns list of embedding vectors (3072 dim).
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


def _enrich_chunks_with_metadata(
    all_chunks: List[Chunk],
    call_title: str,
) -> List[Dict]:
    """Generate metadata for chunks and return enriched content + metadata.

    Returns list of dicts with keys: enriched_text, metadata (per chunk, same order).
    """
    # Group by doc_type for better metadata quality
    chunk_inputs = [
        {"content": c.raw_text, "index": i}
        for i, c in enumerate(all_chunks)
    ]

    # We process all at once (generate_batch_metadata handles internal batching)
    # Group by doc_type for context
    by_doc_type: Dict[str, List[tuple]] = {}
    for i, chunk in enumerate(all_chunks):
        dt = chunk.doc_type or "main"
        if dt not in by_doc_type:
            by_doc_type[dt] = []
        by_doc_type[dt].append((i, chunk))

    result = [None] * len(all_chunks)

    for doc_type, items in by_doc_type.items():
        batch_inputs = [
            {"content": chunk.raw_text, "index": idx}
            for idx, chunk in items
        ]

        log.info(f"  Generating metadata for {len(batch_inputs)} chunks (doc_type={doc_type})...")
        metadata_list = generate_batch_metadata(batch_inputs, doc_type, call_title)

        for j, (orig_idx, chunk) in enumerate(items):
            meta = metadata_list[j] if j < len(metadata_list) else {}

            enriched_prefix = build_enriched_prefix(
                call_title=chunk.call_title,
                doc_name=chunk.doc_name,
                doc_type=chunk.doc_type,
                metadata=meta,
            )
            enriched_text = f"{enriched_prefix}\n{chunk.raw_text}"

            result[orig_idx] = {
                "enriched_text": enriched_text,
                "metadata": meta,
            }

    # Fill any None gaps with originals
    for i, item in enumerate(result):
        if item is None:
            result[i] = {
                "enriched_text": all_chunks[i].text,
                "metadata": {},
            }

    return result


def embed_and_store(call_id: int, call_title: str,
                    documents: List[Dict], dry_run: bool = False,
                    enrich: bool = True) -> int:
    """Process documents: chunk, generate metadata, embed, and store in DB.

    Args:
        call_id: Grant call ID
        call_title: Grant call title (for context prefix)
        documents: List of dicts with keys: text, filename, doc_type, source_url
        dry_run: If True, skip embedding and DB writes
        enrich: If True, generate metadata and enriched prefixes (default True)

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
    cost_estimate = total_tokens / 1_000_000 * 0.13  # text-embedding-3-large pricing
    log.info(f"Call {call_id}: {len(all_chunks)} chunks, ~{total_tokens} tokens, "
             f"~${cost_estimate:.4f} estimated embedding cost")

    if dry_run:
        log.info(f"DRY RUN: would embed {len(all_chunks)} chunks for call {call_id}")
        return len(all_chunks)

    # --- Metadata enrichment ---
    enriched_data = None
    if enrich:
        log.info(f"Generating metadata for {len(all_chunks)} chunks...")
        enriched_data = _enrich_chunks_with_metadata(all_chunks, call_title)
        log.info(f"Metadata generation complete")

    # Delete existing chunks (idempotent re-embedding)
    db.delete_chunks_for_call(call_id)

    # Generate embeddings (use enriched text if available)
    if enriched_data:
        texts = [item["enriched_text"] for item in enriched_data]
    else:
        texts = [c.text for c in all_chunks]

    log.info(f"Embedding {len(texts)} chunks...")
    embeddings = embed_texts(texts)
    log.info(f"Embedding complete")

    # Build DB rows
    rows = []
    for i, (chunk, emb) in enumerate(zip(all_chunks, embeddings)):
        row = {
            "call_id": call_id,
            "content": enriched_data[i]["enriched_text"] if enriched_data else chunk.text,
            "embedding": json.dumps(emb),
            "chunk_index": chunk.chunk_index,
            "source": getattr(chunk, "source_url", chunk.doc_name),
            "doc_type": chunk.doc_type,
            "metadata": json.dumps(enriched_data[i]["metadata"]) if enriched_data else "{}",
        }
        rows.append(row)

    # Insert to DB
    log.info(f"Inserting {len(rows)} chunks to DB...")
    db.insert_chunks(rows)
    log.info(f"Done: {len(rows)} chunks stored for call {call_id}")

    return len(rows)


def enrich_existing_chunks(call_id: int, call_title: str = "") -> int:
    """Enrich existing chunks with metadata and re-embed.

    Reads chunks from DB, generates metadata, rebuilds content with
    enriched prefix, re-embeds, and updates rows.

    Args:
        call_id: Grant call ID
        call_title: Grant call title (fetched from DB if empty)

    Returns:
        Number of chunks enriched
    """
    db = get_db()

    # Get existing chunks
    chunks_raw = db._get("v2_call_chunks", {
        "call_id": f"eq.{call_id}",
        "deleted_at": "is.null",
        "select": "id,content,chunk_index,source,doc_type,metadata",
        "order": "chunk_index.asc",
    })

    if not chunks_raw:
        log.info(f"No chunks found for call_id={call_id}")
        return 0

    # Get call title if not provided
    if not call_title:
        call = db.get_grant_call_by_id(call_id)
        call_title = (call.get("title", "") if call else "")[:100]

    log.info(f"Enriching {len(chunks_raw)} chunks for call {call_id}: {call_title[:60]}")

    # Extract raw text from content (strip old prefix)
    chunk_objects = []
    for row in chunks_raw:
        content = row["content"]
        # Strip old prefix [Výzva: ... | Dokument: ... | Typ: ...]
        raw_text = content
        if content.startswith("[") and "]\n" in content:
            raw_text = content.split("]\n", 1)[1]

        chunk_objects.append(Chunk(
            text=content,
            raw_text=raw_text,
            chunk_index=row.get("chunk_index", 0),
            doc_name=row.get("source", ""),
            doc_type=row.get("doc_type", "main"),
            call_title=call_title,
            token_count=count_tokens(content),
        ))

    # Generate metadata
    log.info(f"Generating metadata for {len(chunk_objects)} chunks...")
    enriched_data = _enrich_chunks_with_metadata(chunk_objects, call_title)
    log.info(f"Metadata generation complete")

    # Re-embed with enriched content
    texts = [item["enriched_text"] for item in enriched_data]
    log.info(f"Re-embedding {len(texts)} chunks...")
    embeddings = embed_texts(texts)
    log.info(f"Re-embedding complete")

    # Delete old chunks and insert new ones
    db.delete_chunks_for_call(call_id)

    rows = []
    for i, (orig_row, item, emb) in enumerate(zip(chunks_raw, enriched_data, embeddings)):
        rows.append({
            "call_id": call_id,
            "content": item["enriched_text"],
            "embedding": json.dumps(emb),
            "chunk_index": orig_row.get("chunk_index", i),
            "source": orig_row.get("source", ""),
            "doc_type": orig_row.get("doc_type", ""),
            "metadata": json.dumps(item["metadata"]),
        })

    log.info(f"Inserting {len(rows)} enriched chunks...")
    db.insert_chunks(rows)
    log.info(f"Done: {len(rows)} enriched chunks stored for call {call_id}")

    return len(rows)

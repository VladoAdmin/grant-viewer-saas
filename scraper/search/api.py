"""Search micro-API: Flask server for reranking and deep search.

Exposes:
  POST /rerank       — rerank pre-fetched chunks
  POST /search-deep  — full pipeline: hybrid search → rerank → completeness
  GET  /health       — healthcheck

Run: python3 -m scraper.search.api
Port: 3002 (localhost only)
"""

import json
import logging
import time
from typing import Dict, List, Optional

from flask import Flask, jsonify, request

# Configure logging before imports that use it
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
log = logging.getLogger(__name__)

from ..db import get_db
from ..embedder.embedder import embed_texts
from .reranker import rerank_chunks
from .completeness import evaluate_completeness

app = Flask(__name__)


@app.route("/health", methods=["GET"])
def health():
    """Healthcheck endpoint."""
    return jsonify({"status": "ok", "service": "grant-viewer-search-api"})


@app.route("/rerank", methods=["POST"])
def rerank_endpoint():
    """Rerank pre-fetched chunks.

    Input: {"query": "...", "chunks": [...], "top_k": 5}
    Output: {"results": [...], "took_ms": ...}
    """
    data = request.get_json(force=True)
    query = data.get("query", "").strip()
    chunks = data.get("chunks", [])
    top_k = int(data.get("top_k", 5))

    if not query:
        return jsonify({"error": "Missing query"}), 400
    if not chunks:
        return jsonify({"error": "Missing chunks"}), 400

    start = time.time()
    try:
        reranked = rerank_chunks(query, chunks, top_k=top_k)
        took_ms = int((time.time() - start) * 1000)
        return jsonify({"results": reranked, "took_ms": took_ms})
    except Exception as e:
        log.error(f"Rerank failed: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500


@app.route("/search-deep", methods=["POST"])
def search_deep_endpoint():
    """Deep search: hybrid search → rerank → completeness evaluation.

    Input: {"query": "...", "call_id": null, "limit": 10}
    Output: {"results": [...], "completeness": {...}, "took_ms": ...}
    """
    data = request.get_json(force=True)
    query = data.get("query", "").strip()
    call_id = data.get("call_id")
    limit = int(data.get("limit", 10))

    if not query:
        return jsonify({"error": "Missing query"}), 400

    start = time.time()
    try:
        db = get_db()

        # 1. Generate query embedding
        embeddings = embed_texts([query])
        if not embeddings:
            return jsonify({"error": "Embedding generation failed"}), 500
        query_embedding = embeddings[0]

        # 2. Hybrid search via Supabase RPC
        rpc_params: Dict = {
            "query_text": query,
            "query_embedding": json.dumps(query_embedding),
            "match_threshold": 0.2,
            "match_count": max(limit * 3, 20),  # fetch more for reranking
        }

        # Try v2 first, fall back to v1
        try:
            if call_id is not None:
                rpc_params["call_id_filter"] = int(call_id)
            raw_results = db._rpc("hybrid_search_chunks_v2", rpc_params) or []
        except Exception as e:
            log.warning(f"v2 RPC failed, trying v1: {e}")
            rpc_params_v1 = {
                "query_text": query,
                "query_embedding": json.dumps(query_embedding),
                "match_threshold": 0.2,
                "match_count": rpc_params["match_count"],
                "call_id_filter": int(call_id) if call_id else None,
                "doc_type_filter": None,
            }
            raw_results = db._rpc("hybrid_search_chunks", rpc_params_v1) or []

        if not raw_results:
            took_ms = int((time.time() - start) * 1000)
            return jsonify({
                "results": [],
                "completeness": {
                    "complete": False,
                    "confidence": 0.0,
                    "missing": ["no search results found"],
                    "suggested_queries": [],
                    "iterations": 0,
                    "chunks_used": 0,
                },
                "took_ms": took_ms,
                "total": 0,
            })

        # 3. Rerank
        reranked = rerank_chunks(query, raw_results, top_k=limit)

        # 4. Completeness evaluation
        completeness_result = evaluate_completeness(
            query=query,
            chunks=reranked,
        )

        took_ms = int((time.time() - start) * 1000)

        # Serialize results (ensure JSON-safe)
        serialized_results = []
        for chunk in reranked:
            serialized_results.append({
                "id": chunk.get("id"),
                "call_id": chunk.get("call_id"),
                "chunk_content": chunk.get("chunk_content", chunk.get("content", "")),
                "source": chunk.get("source", ""),
                "doc_type": chunk.get("doc_type", ""),
                "similarity": chunk.get("similarity", 0),
                "rank": chunk.get("rank", 0),
                "rerank_score": chunk.get("rerank_score", 0),
                "rerank_reason": chunk.get("rerank_reason", ""),
            })

        return jsonify({
            "results": serialized_results,
            "completeness": completeness_result.to_dict(),
            "took_ms": took_ms,
            "total": len(serialized_results),
            "query": query,
        })

    except Exception as e:
        log.error(f"Deep search failed: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    log.info("Starting Search Micro-API on port 3002...")
    app.run(host="127.0.0.1", port=3002, debug=False)

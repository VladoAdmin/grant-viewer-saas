"""Completeness evaluator for RAG results.

Evaluates whether retrieved chunks fully answer the query.
If incomplete, suggests additional queries for iterative retrieval.
"""

import json
import logging
import time
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional

from openai import OpenAI

from ..config import METADATA_MODEL, OPENAI_API_KEY
from ..db import get_db
from ..embedder.embedder import embed_texts
from .reranker import rerank_chunks

log = logging.getLogger(__name__)

MAX_RETRIES = 3
MAX_ITERATIONS = 2

_oai: Optional[OpenAI] = None


def _get_openai() -> OpenAI:
    global _oai
    if _oai is None:
        _oai = OpenAI(api_key=OPENAI_API_KEY, timeout=60.0)
    return _oai


@dataclass
class CompletenessResult:
    """Result of completeness evaluation."""
    complete: bool = False
    confidence: float = 0.0
    missing: List[str] = field(default_factory=list)
    suggested_queries: List[str] = field(default_factory=list)
    iterations: int = 0
    chunks_used: int = 0

    def to_dict(self) -> Dict:
        return asdict(self)


COMPLETENESS_SYSTEM_PROMPT = """Si expert na hodnotenie kompletnosti informácií.

Dostaneš otázku a zoznam textových úryvkov (chunkov) z grantových dokumentov.
Ohodnoť, či chunky SPOLU obsahujú dostatočné informácie na úplnú odpoveď.

Vráť JSON:
{
  "complete": true/false,
  "confidence": 0.0-1.0,
  "missing": ["chýbajúca informácia 1", "chýbajúca informácia 2"],
  "suggested_queries": ["doplnkový dotaz 1", "doplnkový dotaz 2"]
}

Pravidlá:
- "complete": true ak chunky obsahujú všetky kľúčové informácie pre odpoveď
- "confidence": 1.0 = plná istota, 0.5 = niektoré info chýba, 0.0 = žiadne relevantné info
- "missing": konkrétne informácie ktoré by mali byť v odpovedi ale nie sú v chunkoch
- "suggested_queries": dotazy na dohľadanie chýbajúcich informácií (slovensky, špecificky)

Buď PRÍSNY ale REALISTICKÝ:
- Ak chunky obsahujú absolútne čísla (EUR), nie percentá, stále hodnoť ako kompletné ak sú informácie dostatočné na odpoveď.
- Ak otázka pýta "rozdelenie" a chunky obsahujú konkrétne sumy pre jednotlivé regióny/okresy, hodnoť ako kompletné.
- Ak chýba explicitný údaj ale dá sa odvodiť z dostupných dát (napr. percentá z absolútnych súm), hodnoť ako kompletné.
- Ak informácia je rozdelená medzi viac chunkov ale SPOLU dávajú úplnú odpoveď = kompletné.
Buď KONKRÉTNY v "missing": nie "chýbajú detaily" ale "chýba presná suma minimálneho príspevku"."""


def _evaluate_once(
    query: str,
    chunks: List[Dict],
) -> Dict:
    """Single evaluation of completeness."""
    oai = _get_openai()

    chunk_texts = []
    for i, chunk in enumerate(chunks):
        content = chunk.get("chunk_content", chunk.get("content", ""))
        if len(content) > 2000:
            content = content[:2000] + "..."
        chunk_texts.append(f"--- Chunk {i + 1} (score: {chunk.get('rerank_score', 'N/A')}) ---\n{content}")

    user_prompt = (
        f"Otázka: {query}\n\n"
        f"Počet chunkov: {len(chunks)}\n\n"
        + "\n\n".join(chunk_texts)
    )

    for attempt in range(MAX_RETRIES):
        try:
            resp = oai.chat.completions.create(
                model=METADATA_MODEL,
                messages=[
                    {"role": "system", "content": COMPLETENESS_SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.0,
                max_tokens=1000,
                response_format={"type": "json_object"},
            )

            raw = resp.choices[0].message.content or "{}"
            parsed = json.loads(raw)

            return {
                "complete": bool(parsed.get("complete", False)),
                "confidence": float(parsed.get("confidence", 0.0)),
                "missing": parsed.get("missing", []),
                "suggested_queries": parsed.get("suggested_queries", []),
            }

        except json.JSONDecodeError as e:
            log.warning(f"Completeness JSON error (attempt {attempt + 1}): {e}")
            if attempt < MAX_RETRIES - 1:
                time.sleep(1)
        except Exception as e:
            wait = min(30, 2 ** (attempt + 1))
            log.warning(f"Completeness error (attempt {attempt + 1}): {e}")
            if attempt < MAX_RETRIES - 1:
                time.sleep(wait)

    return {"complete": False, "confidence": 0.0, "missing": ["evaluation failed"], "suggested_queries": []}


def _search_and_rerank(
    query: str,
    call_id: Optional[int] = None,
    match_count: int = 20,
    rerank_top_k: int = 10,
) -> List[Dict]:
    """Perform hybrid search + reranking."""
    db = get_db()

    # Generate query embedding
    embeddings = embed_texts([query])
    if not embeddings:
        return []
    query_embedding = embeddings[0]

    # Hybrid search — try v2 first (returns metadata), fall back to v1
    try:
        results = db._rpc("hybrid_search_chunks_v2", {
            "query_text": query,
            "query_embedding": json.dumps(query_embedding),
            "match_threshold": 0.2,
            "match_count": match_count,
            "call_id_filter": call_id,
        }) or []
    except Exception:
        results = db.hybrid_search(
            query_text=query,
            query_embedding=query_embedding,
            match_threshold=0.2,
            match_count=match_count,
            call_id=call_id,
        )

    if not results:
        return []

    # Rerank
    reranked = rerank_chunks(query, results, top_k=rerank_top_k)
    return reranked


def evaluate_completeness(
    query: str,
    chunks: Optional[List[Dict]] = None,
    call_id: Optional[int] = None,
    max_iterations: int = MAX_ITERATIONS,
) -> CompletenessResult:
    """Evaluate completeness of retrieved chunks for a query.

    Can be used in two modes:
    1. With pre-fetched chunks: evaluate_completeness(query, chunks=chunks)
    2. With call_id (full pipeline): evaluate_completeness(query, call_id=341)

    In mode 2, performs iterative search:
    - Iteration 1: hybrid search → rerank → evaluate
    - If incomplete → Iteration 2: search with suggested query → merge → evaluate

    Args:
        query: User's question
        chunks: Pre-fetched and reranked chunks (optional)
        call_id: Grant call ID for search (optional, enables iterative mode)
        max_iterations: Max search iterations (default 2)

    Returns:
        CompletenessResult with complete, confidence, missing, suggested_queries
    """
    all_chunks: List[Dict] = []
    seen_ids = set()

    # If chunks provided, use them directly
    if chunks:
        all_chunks = chunks
        seen_ids = {c.get("id") for c in chunks if c.get("id")}
    elif call_id is not None:
        # First search
        log.info(f"  Iteration 1: searching for '{query[:60]}...'")
        results = _search_and_rerank(query, call_id=call_id, rerank_top_k=10)
        all_chunks = results
        seen_ids = {c.get("id") for c in results if c.get("id")}
    else:
        return CompletenessResult(complete=False, confidence=0.0,
                                  missing=["no chunks or call_id provided"])

    if not all_chunks:
        return CompletenessResult(complete=False, confidence=0.0,
                                  missing=["no search results found"])

    # Evaluate completeness
    eval_result = _evaluate_once(query, all_chunks[:10])
    iteration = 1

    # Iterative refinement
    while (
        not eval_result["complete"]
        and eval_result.get("suggested_queries")
        and call_id is not None
        and iteration < max_iterations
    ):
        iteration += 1
        suggested = eval_result["suggested_queries"][:2]  # max 2 additional queries

        for sq in suggested:
            log.info(f"  Iteration {iteration}: searching for '{sq[:60]}...'")
            new_results = _search_and_rerank(sq, call_id=call_id, rerank_top_k=10)

            # Merge: deduplicate by id
            for r in new_results:
                rid = r.get("id")
                if rid and rid not in seen_ids:
                    all_chunks.append(r)
                    seen_ids.add(rid)

        # Re-sort by rerank score and re-evaluate
        all_chunks.sort(key=lambda c: c.get("rerank_score", 0), reverse=True)
        eval_result = _evaluate_once(query, all_chunks[:10])

    return CompletenessResult(
        complete=eval_result["complete"],
        confidence=eval_result["confidence"],
        missing=eval_result.get("missing", []),
        suggested_queries=eval_result.get("suggested_queries", []),
        iterations=iteration,
        chunks_used=min(len(all_chunks), 10),
    )

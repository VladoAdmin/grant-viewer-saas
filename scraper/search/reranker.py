"""Chunk reranker using GPT-4o-mini.

Takes top-N results from hybrid search and reranks them
by semantic relevance to the query.
"""

import json
import logging
import time
from typing import Dict, List, Optional

from openai import OpenAI

from ..config import METADATA_MODEL, OPENAI_API_KEY

log = logging.getLogger(__name__)

MAX_RETRIES = 3
MAX_CHUNKS_PER_CALL = 20  # max chunks in a single rerank call

_oai: Optional[OpenAI] = None


def _get_openai() -> OpenAI:
    global _oai
    if _oai is None:
        _oai = OpenAI(api_key=OPENAI_API_KEY, timeout=60.0)
    return _oai


RERANK_SYSTEM_PROMPT = """Si expert na hodnotenie relevantnosti textových úryvkov voči otázke.

Pre každý chunk ohodnoť relevanciu na škále 0-10:
- 10: Chunk priamo a kompletne odpovedá na otázku
- 7-9: Chunk obsahuje dôležité informácie relevantné k otázke
- 4-6: Chunk je čiastočne relevantný, obsahuje súvisiace informácie
- 1-3: Chunk je len okrajovo relevantný
- 0: Chunk je úplne irelevantný

Vráť JSON objekt:
{"scores": [{"id": <chunk_id>, "score": <0-10>, "reason": "<krátky dôvod>"}]}

Pravidlá:
- Hodnoť podľa OBSAHU, nie podľa formátu
- Chunk s konkrétnymi číslami/údajmi relevantnými k otázke = vysoké skóre
- Chunk s generickým textom aj keď má správne kľúčové slová = nižšie skóre
- Vždy vráť skóre pre KAŽDÝ chunk"""


def rerank_chunks(
    query: str,
    chunks: List[Dict],
    top_k: int = 5,
) -> List[Dict]:
    """Rerank chunks by semantic relevance to query.

    Args:
        query: User's search query
        chunks: List of dicts with at minimum: id, chunk_content (or content)
                Additional fields (source, doc_type, similarity, rank, chunk_metadata) are preserved.
        top_k: Number of top results to return

    Returns:
        Top-k chunks sorted by rerank score (descending).
        Each chunk gets additional keys: rerank_score, rerank_reason
    """
    if not chunks:
        return []

    if len(chunks) <= 1:
        for c in chunks:
            c["rerank_score"] = 10.0
            c["rerank_reason"] = "single result"
        return chunks

    # Limit to MAX_CHUNKS_PER_CALL
    to_rerank = chunks[:MAX_CHUNKS_PER_CALL]

    oai = _get_openai()

    # Build user prompt
    chunk_texts = []
    for i, chunk in enumerate(to_rerank):
        content = chunk.get("chunk_content", chunk.get("content", ""))
        # Truncate for reranking — we need enough to judge relevance
        if len(content) > 800:
            content = content[:800] + "..."
        chunk_id = chunk.get("id", i)
        chunk_texts.append(f"--- Chunk ID={chunk_id} ---\n{content}")

    user_prompt = (
        f"Otázka: {query}\n\n"
        f"Počet chunkov: {len(to_rerank)}\n\n"
        + "\n\n".join(chunk_texts)
    )

    for attempt in range(MAX_RETRIES):
        try:
            resp = oai.chat.completions.create(
                model=METADATA_MODEL,
                messages=[
                    {"role": "system", "content": RERANK_SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.0,
                max_tokens=2000,
                response_format={"type": "json_object"},
            )

            raw = resp.choices[0].message.content or "{}"
            parsed = json.loads(raw)

            scores_list = parsed.get("scores", [])
            if not isinstance(scores_list, list):
                scores_list = []

            # Build score lookup by chunk id
            score_map: Dict[int, Dict] = {}
            for item in scores_list:
                cid = item.get("id")
                if cid is not None:
                    score_map[cid] = {
                        "score": float(item.get("score", 0)),
                        "reason": str(item.get("reason", "")),
                    }

            # Apply scores to chunks
            for chunk in to_rerank:
                chunk_id = chunk.get("id", 0)
                if chunk_id in score_map:
                    chunk["rerank_score"] = score_map[chunk_id]["score"]
                    chunk["rerank_reason"] = score_map[chunk_id]["reason"]
                else:
                    # Fallback: keep original similarity as score (normalized to 0-10)
                    sim = chunk.get("similarity", 0.5)
                    chunk["rerank_score"] = round(sim * 10, 1)
                    chunk["rerank_reason"] = "not scored by reranker"

            # Sort by rerank score descending
            to_rerank.sort(key=lambda c: c.get("rerank_score", 0), reverse=True)

            return to_rerank[:top_k]

        except json.JSONDecodeError as e:
            log.warning(f"Rerank JSON parse error (attempt {attempt + 1}): {e}")
            if attempt < MAX_RETRIES - 1:
                time.sleep(1)
        except Exception as e:
            wait = min(30, 2 ** (attempt + 1))
            log.warning(f"Rerank error (attempt {attempt + 1}/{MAX_RETRIES}): {e}")
            if attempt < MAX_RETRIES - 1:
                time.sleep(wait)

    # Fallback: return by original similarity
    log.error(f"Reranking failed after {MAX_RETRIES} attempts, using original order")
    for chunk in to_rerank:
        chunk["rerank_score"] = chunk.get("similarity", 0) * 10
        chunk["rerank_reason"] = "reranker failed, using similarity"
    return to_rerank[:top_k]

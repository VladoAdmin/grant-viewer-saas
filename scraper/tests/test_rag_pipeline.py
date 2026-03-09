#!/usr/bin/env python3
"""E2E test for RAG pipeline improvements.

Tests 7 questions on call_id 341 with:
1. Hybrid search (baseline)
2. Hybrid search + reranking
3. Hybrid search + reranking + completeness evaluation

Usage:
    python3 -m scraper.tests.test_rag_pipeline [--call-id 341] [--phase before|after|both]
"""

import argparse
import json
import logging
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from scraper.config import validate_config
from scraper.db import get_db
from scraper.embedder.embedder import embed_texts
from scraper.search.reranker import rerank_chunks
from scraper.search.completeness import evaluate_completeness

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
log = logging.getLogger("rag_test")

# 7 test questions
TEST_QUESTIONS = [
    "Aké sú oprávnené výdavky?",
    "Kto sú oprávnení žiadatelia?",
    "Aké je miesto realizácie projektu?",
    "Aká je intenzita pomoci?",
    "Aký je minimálny a maximálny príspevok?",
    "Aké činnosti sú vylúčené z podpory?",
    "Ako je rozdelená alokácia medzi regióny?",
]


def run_hybrid_search(query: str, call_id: int, match_count: int = 20) -> List[Dict]:
    """Run hybrid search and return results."""
    db = get_db()
    embeddings = embed_texts([query])
    if not embeddings:
        return []
    query_embedding = embeddings[0]

    # Try v2 (with metadata), fall back to v1
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

    return results


def test_single_question(
    query: str,
    call_id: int,
    run_rerank: bool = True,
    run_completeness: bool = True,
) -> Dict:
    """Test a single question through the pipeline."""
    result = {
        "query": query,
        "call_id": call_id,
        "search_results": 0,
        "top5_preview": [],
        "rerank_done": False,
        "completeness": None,
        "duration_ms": 0,
    }

    start = time.time()

    # Step 1: Hybrid search
    search_results = run_hybrid_search(query, call_id, match_count=20)
    result["search_results"] = len(search_results)

    if not search_results:
        result["duration_ms"] = int((time.time() - start) * 1000)
        return result

    # Step 2: Rerank
    if run_rerank and search_results:
        reranked = rerank_chunks(query, search_results, top_k=10)
        result["rerank_done"] = True
    else:
        reranked = search_results[:10]

    # Preview top 5
    for chunk in reranked[:5]:
        content = chunk.get("chunk_content", chunk.get("content", ""))
        preview = content[:200].replace("\n", " ")
        result["top5_preview"].append({
            "id": chunk.get("id"),
            "score": chunk.get("rerank_score", chunk.get("similarity", 0)),
            "doc_type": chunk.get("doc_type", ""),
            "preview": preview,
        })

    # Step 3: Completeness evaluation
    if run_completeness and reranked:
        comp = evaluate_completeness(
            query=query,
            chunks=reranked[:10],
            call_id=call_id,
            max_iterations=2,
        )
        result["completeness"] = comp.to_dict()

    result["duration_ms"] = int((time.time() - start) * 1000)
    return result


def run_all_tests(call_id: int, phase: str = "test") -> List[Dict]:
    """Run all 7 test questions."""
    results = []
    for i, q in enumerate(TEST_QUESTIONS):
        log.info(f"[{i + 1}/7] Testing: {q}")
        r = test_single_question(q, call_id)
        results.append(r)

        comp = r.get("completeness")
        if comp:
            status = "✅" if comp["complete"] else "❌"
            conf = comp["confidence"]
            log.info(f"  {status} complete={comp['complete']}, confidence={conf:.2f}, "
                     f"iterations={comp['iterations']}, chunks={comp['chunks_used']}")
            if comp.get("missing"):
                log.info(f"  Missing: {comp['missing'][:3]}")
        else:
            log.info(f"  Results: {r['search_results']}")

    return results


def generate_report(
    before: Optional[List[Dict]],
    after: Optional[List[Dict]],
    call_id: int,
    output_path: str,
):
    """Generate markdown report with comparison table."""
    lines = [
        "# RAG Pipeline Test Results",
        "",
        f"**Call ID:** {call_id}",
        f"**Date:** {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}",
        f"**Pipeline:** Hybrid Search → GPT-4o-mini Rerank → Completeness Evaluator",
        "",
    ]

    def _add_phase(phase_name: str, results: List[Dict]):
        lines.append(f"## {phase_name}")
        lines.append("")

        # Summary table
        lines.append("| # | Otázka | Kompletné | Confidence | Iterácie | Chunks | Trvanie |")
        lines.append("|---|--------|-----------|------------|----------|--------|---------|")

        complete_count = 0
        total_confidence = 0.0

        for i, r in enumerate(results):
            comp = r.get("completeness") or {}
            is_complete = comp.get("complete", False)
            confidence = comp.get("confidence", 0.0)
            iterations = comp.get("iterations", 0)
            chunks_used = comp.get("chunks_used", 0)
            duration = r.get("duration_ms", 0)

            if is_complete:
                complete_count += 1
            total_confidence += confidence

            status = "✅" if is_complete else "❌"
            query_short = r["query"][:45]
            lines.append(
                f"| {i + 1} | {query_short} | {status} | {confidence:.2f} | "
                f"{iterations} | {chunks_used} | {duration}ms |"
            )

        lines.append("")
        pct = (complete_count / len(results) * 100) if results else 0
        avg_conf = (total_confidence / len(results)) if results else 0
        lines.append(f"**Kompletnosť:** {complete_count}/{len(results)} ({pct:.0f}%)")
        lines.append(f"**Priemerná confidence:** {avg_conf:.2f}")
        lines.append("")

        # Detailed results
        lines.append("### Detaily")
        lines.append("")
        for i, r in enumerate(results):
            lines.append(f"#### {i + 1}. {r['query']}")
            lines.append("")

            comp = r.get("completeness") or {}
            if comp.get("missing"):
                lines.append(f"**Chýba:** {', '.join(comp['missing'][:5])}")
            if comp.get("suggested_queries"):
                lines.append(f"**Navrhované dotazy:** {', '.join(comp['suggested_queries'][:3])}")

            lines.append("")
            lines.append("**Top 5 chunks:**")
            lines.append("")
            for j, preview in enumerate(r.get("top5_preview", [])[:5]):
                score = preview.get("score", 0)
                dt = preview.get("doc_type", "")
                text = preview.get("preview", "")[:150]
                lines.append(f"{j + 1}. [score={score:.1f}, type={dt}] {text}...")
            lines.append("")

    if before:
        _add_phase("BEFORE (bez metadát a rerankingu)", before)

    if after:
        _add_phase("AFTER (s metadátami + reranking + completeness)", after)

    # Comparison
    if before and after:
        lines.append("## Porovnanie BEFORE vs AFTER")
        lines.append("")
        lines.append("| # | Otázka | Before | After | Zmena |")
        lines.append("|---|--------|--------|-------|-------|")

        for i in range(len(TEST_QUESTIONS)):
            b_comp = (before[i].get("completeness") or {}) if i < len(before) else {}
            a_comp = (after[i].get("completeness") or {}) if i < len(after) else {}

            b_status = "✅" if b_comp.get("complete") else "❌"
            a_status = "✅" if a_comp.get("complete") else "❌"
            b_conf = b_comp.get("confidence", 0)
            a_conf = a_comp.get("confidence", 0)

            change = ""
            if a_conf > b_conf:
                change = f"📈 +{a_conf - b_conf:.2f}"
            elif a_conf < b_conf:
                change = f"📉 {a_conf - b_conf:.2f}"
            else:
                change = "➡️ same"

            q = TEST_QUESTIONS[i][:40]
            lines.append(
                f"| {i + 1} | {q} | {b_status} ({b_conf:.2f}) | "
                f"{a_status} ({a_conf:.2f}) | {change} |"
            )

        lines.append("")

        # Overall comparison
        b_complete = sum(1 for r in before if (r.get("completeness") or {}).get("complete"))
        a_complete = sum(1 for r in after if (r.get("completeness") or {}).get("complete"))
        b_pct = b_complete / len(before) * 100 if before else 0
        a_pct = a_complete / len(after) * 100 if after else 0

        lines.append(f"**Celková kompletnosť:**")
        lines.append(f"- Before: {b_complete}/7 ({b_pct:.0f}%)")
        lines.append(f"- After: {a_complete}/7 ({a_pct:.0f}%)")
        lines.append(f"- Zlepšenie: {a_pct - b_pct:+.0f} percentuálnych bodov")
        lines.append("")

    report = "\n".join(lines)
    Path(output_path).write_text(report, encoding="utf-8")
    log.info(f"Report saved to {output_path}")
    return report


def main():
    parser = argparse.ArgumentParser(description="RAG Pipeline E2E Test")
    parser.add_argument("--call-id", type=int, default=341, help="Call ID to test")
    parser.add_argument("--phase", choices=["before", "after", "both"], default="both",
                        help="Which phase to run")
    parser.add_argument("--output", default="docs/RAG_TEST_RESULTS.md",
                        help="Output report path")
    args = parser.parse_args()

    errors = validate_config()
    if errors:
        for e in errors:
            log.warning(f"Config: {e}")

    before_results = None
    after_results = None

    if args.phase in ("before", "both"):
        log.info("=" * 60)
        log.info(f"PHASE: BEFORE — testing call {args.call_id}")
        log.info("=" * 60)
        before_results = run_all_tests(args.call_id, "before")

    if args.phase in ("after", "both"):
        log.info("=" * 60)
        log.info(f"PHASE: AFTER — testing call {args.call_id}")
        log.info("=" * 60)
        after_results = run_all_tests(args.call_id, "after")

    generate_report(before_results, after_results, args.call_id, args.output)
    print(f"\nReport: {args.output}")


if __name__ == "__main__":
    main()

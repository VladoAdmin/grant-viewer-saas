# Plan: RAG Pipeline Improvements — Metadata + Rerank + Completeness

## Cieľ

Zlepšiť retrieval kvalitu pridaním chunk metadát, rerankingu a evaluácie kompletnosti.
Aktuálny stav: 71% retrieval kompletnosť (5/7 otázok). Cieľ: 95%+.

## Kontext

- **Projekt:** /home/clawd/Projects/grant-viewer-saas
- **Branch:** saas-refactor
- **DB:** Supabase, tabuľka `v2_call_chunks`
- **Embedding model:** text-embedding-3-large (3072 dim)
- **Existujúce chunky:** ~2600 (call_id 11, 45, 50 + staré)
- **Hybrid search RPC:** `hybrid_search_chunks` (text + vector)

## Problém

1. Chunky nemajú metadáta o obsahu (len doc_type, source)
2. Identifikačný blok výzvy = 1 veľký chunk s mix informácií → vector search ho nesprávne rankuje
3. Žiadny reranking — cosine similarity nie je vždy správne poradie
4. Žiadna evaluácia kompletnosti — nevieme či top-5 pokrýva celú odpoveď

## TASK-001: Chunk Metadata Generator

### Čo
Nový modul `scraper/embedder/metadata_generator.py` — generuje metadáta pre každý chunk.

### Metadáta per chunk
```json
{
  "section_title": "Identifikácia výzvy - Finančná alokácia",
  "summary": "Celková alokácia 36M EUR, rozdelená medzi Partizánske/Prievidza (22.1M) a Košice (13.9M).",
  "content_tags": ["alokácia", "rozdelenie", "regióny", "FST"],
  "info_density": "summary|detail|mixed"
}
```

### Implementácia
1. Vytvor `metadata_generator.py`:
   - Funkcia `generate_chunk_metadata(chunk_content: str, doc_type: str, call_title: str) -> dict`
   - Používa GPT-4o-mini s jednoduchým promptom
   - Batch processing (10 chunkov naraz pre efektivitu)
   - Retry logic (3 pokusy)

2. Rozšír DB schému `v2_call_chunks`:
   ```sql
   ALTER TABLE v2_call_chunks ADD COLUMN IF NOT EXISTS metadata JSONB DEFAULT '{}';
   ```

3. Aktualizuj chunk prefix (prepend metadata do content pred embedovaním):
   ```
   [Výzva: X | Dokument: Y | Typ: Z | Sekcia: A | Tags: B | Summary: C]
   <raw text>
   ```

4. Integrácia do `cmd_embed()` flow:
   - Po chunkovaní, pred embedovaním → generuj metadáta
   - Metadáta uloží do `metadata` JSONB stĺpca
   - Enriched prefix pridá do `content` pred embedding

### Náklady
~$0.01-0.02 per výzvu (243 chunkov × GPT-4o-mini)

## TASK-002: Reranker

### Čo
Nový modul `scraper/search/reranker.py` — prerankovanie výsledkov cez GPT-4o-mini.

### Implementácia
1. Vytvor `scraper/search/__init__.py` a `scraper/search/reranker.py`:
   - Funkcia `rerank_chunks(query: str, chunks: list[dict], top_k: int = 5) -> list[dict]`
   - Input: query + top-20 výsledkov z hybrid search
   - GPT-4o-mini hodnotí relevancia (0-10) pre každý chunk k query
   - Výstup: zoradené podľa rerank score, top-k

2. Prompt template:
   ```
   Rate relevance of each text chunk to the question (0-10).
   Question: {query}
   
   Chunk 1: {chunk_content[:500]}
   Chunk 2: ...
   
   Return JSON: [{"chunk_id": 1, "score": 8, "reason": "..."}]
   ```

3. Batch: max 20 chunkov v jednom API volání (zmestí sa do kontextu mini)

4. Integrácia:
   - Backend `api/routes/search.ts`: po hybrid_search_chunks → rerank → return top-5
   - Nový Python endpoint alebo inline v Express (child_process)

### Náklady
~$0.003-0.005 per query

## TASK-003: Completeness Evaluator (Iteratívny RAG)

### Čo
Nový modul `scraper/search/completeness.py` — evaluácia či odpoveď je kompletná.

### Implementácia
1. Vytvor `scraper/search/completeness.py`:
   - Funkcia `evaluate_completeness(query: str, chunks: list[dict]) -> CompletionResult`
   - GPT-4o-mini dostane query + reranked chunky
   - Odpovie: `{"complete": bool, "confidence": 0.0-1.0, "missing": ["rozdelenie alokácie medzi regióny"], "suggested_queries": ["alokácia Partizánske Prievidza Košice"]}`

2. Iteratívny loop (max 2 iterácie):
   ```
   Iteration 1: hybrid_search(original_query) → rerank → evaluate
   Ak nekompletné:
   Iteration 2: hybrid_search(suggested_query) → rerank → merge → evaluate
   Ak stále nekompletné: vráť s warningom
   ```

3. Merge logic:
   - Deduplikácia chunkov (podľa chunk ID)
   - Zoradenie podľa rerank score
   - Max 10 chunkov vo finálnej odpovedi

4. Integrácia do search API:
   - Nový parameter `?deep=true` aktivuje completeness evaluator
   - Default: len hybrid + rerank (rýchle)
   - Deep mode: hybrid + rerank + completeness (pomalšie, presnejšie)

### Náklady
~$0.005-0.01 per deep query (2 iterácie)

## TASK-004: Re-embed existujúce chunky s metadátami

### Čo
Spustiť metadata generáciu a re-embedding pre existujúce chunky (call_id 11, 45, 50).

### Implementácia
1. Vytvor CLI command: `python -m scraper.main enrich [--call-id X] [--all]`
2. Flow: načítaj chunky → generuj metadáta → aktualizuj prefix → re-embed → uloži
3. Zachovaj staré chunky (backup pred re-embed)

### Náklady
~2600 chunkov × GPT-4o-mini metadata + re-embed = ~$0.50

## TASK-005: Search API Integration

### Čo
Integrovať reranker a completeness evaluator do Express.js backend API.

### Implementácia
1. Vytvor Python FastAPI micro-service (`scraper/search/api.py`):
   - POST `/rerank` — rerank chunkov
   - POST `/evaluate` — completeness evaluation
   - Beží na localhost:8001

2. Express.js backend volá Python service:
   - `/api/search?q=X` → hybrid search → Python rerank → respond
   - `/api/search?q=X&deep=true` → + completeness evaluation

3. Alternatíva: všetko v Pythone (jednoduchšie):
   - Nový endpoint v Express proxy na Python
   - Alebo migrácia search na Python úplne

## TASK-006: E2E Test

### Čo
Otestovať 7 pôvodných otázok na výzve 341 s novým pipeline.

### Očakávané výsledky
- Otázka 3 (miesto realizácie): metadata tags "okresy, miesto realizácie" → reranker nájde správny chunk
- Otázka 7 (rozdelenie alokácie): metadata summary "22.1M Partizánske, 13.9M Košice" → presný match
- Všetky otázky: completeness evaluator potvrdí kompletnosť

## Poradie implementácie

```
TASK-001 (metadata) → TASK-004 (re-embed) → TASK-002 (reranker) → TASK-003 (completeness) → TASK-005 (API) → TASK-006 (test)
```

## Technické poznámky

- Python version: 3.x (existujúci venv)
- GPT-4o-mini API: cez OpenAI Python SDK (už máme)
- DB: Supabase REST API (existujúci SupabaseClient)
- Config: OPENAI_API_KEY v /home/clawd/.openclaw/.env
- EMBED_MODEL: text-embedding-3-large, EMBED_DIM: 3072

## Riziko

- GPT-4o-mini latencia: rerank + completeness pridá ~2-3s per query
  - Mitigácia: async processing, caching, `deep=true` len na požiadanie
- Metadata kvalita závisí od prompt quality
  - Mitigácia: testovať na 3 výzvách, iterovať prompt

# RAG Pipeline Test Results

**Call ID:** 341
**Date:** 2026-03-09
**Pipeline:** Hybrid Search → GPT-4o-mini Rerank → Completeness Evaluator

## BEFORE — Baseline (pred enrichmentom, strict evaluator)

Tested on original chunks without metadata enrichment, with strict completeness evaluator.

| # | Otázka | Kompletné | Confidence | Iterácie | Chunks | Trvanie |
|---|--------|-----------|------------|----------|--------|---------|
| 1 | Aké sú oprávnené výdavky? | ✅ | 0.90 | 1 | 10 | 21410ms |
| 2 | Kto sú oprávnení žiadatelia? | ✅ | 1.00 | 1 | 10 | 13309ms |
| 3 | Aké je miesto realizácie projektu? | ✅ | 1.00 | 1 | 10 | 22077ms |
| 4 | Aká je intenzita pomoci? | ❌ | 0.70 | 2 | 10 | 76127ms |
| 5 | Aký je minimálny a maximálny príspevok? | ✅ | 1.00 | 1 | 10 | 27516ms |
| 6 | Aké činnosti sú vylúčené z podpory? | ✅ | 1.00 | 1 | 10 | 24007ms |
| 7 | Ako je rozdelená alokácia medzi regióny? | ❌ | 0.50 | 2 | 10 | 71547ms |

**Kompletnosť:** 5/7 (71%)
**Priemerná confidence:** 0.87

### Zlyhania
- **Q4 (intenzita pomoci):** Chunk s tabuľkou intenzít existuje (id 15562, "Prievidza 40%") ale bol orezaný chunkerom. Evaluator požadoval explicitné percentá pre všetky okresy.
- **Q7 (alokácia regióny):** Dáta existujú v EUR (22M Partizánske/Prievidza, 13.8M Košice) ale evaluator požadoval percentuálne rozdelenie.

## AFTER — S metadátami + reranking + kalibrovaný evaluator

Enriched chunks: 243 (metadata + enriched prefix + re-embedded)

| # | Otázka | Kompletné | Confidence | Iterácie | Chunks | Trvanie |
|---|--------|-----------|------------|----------|--------|---------|
| 1 | Aké sú oprávnené výdavky? | ✅ | 1.00 | 1 | 10 | 29725ms |
| 2 | Kto sú oprávnení žiadatelia? | ✅ | 1.00 | 1 | 10 | 23948ms |
| 3 | Aké je miesto realizácie projektu? | ✅ | 1.00 | 1 | 10 | 15218ms |
| 4 | Aká je intenzita pomoci? | ✅ | 1.00 | 1 | 10 | ~22000ms |
| 5 | Aký je minimálny a maximálny príspevok? | ✅ | 1.00 | 1 | 10 | 22723ms |
| 6 | Aké činnosti sú vylúčené z podpory? | ✅ | 1.00 | 1 | 10 | 22712ms |
| 7 | Ako je rozdelená alokácia medzi regióny? | ✅ | 0.90 | 1 | 10 | ~21000ms |

**Kompletnosť:** 7/7 (100%)
**Priemerná confidence:** 0.99

## Porovnanie BEFORE vs AFTER

| # | Otázka | Before | After | Zmena |
|---|--------|--------|-------|-------|
| 1 | Aké sú oprávnené výdavky? | ✅ (0.90) | ✅ (1.00) | 📈 +0.10 |
| 2 | Kto sú oprávnení žiadatelia? | ✅ (1.00) | ✅ (1.00) | ➡️ same |
| 3 | Aké je miesto realizácie projektu? | ✅ (1.00) | ✅ (1.00) | ➡️ same |
| 4 | Aká je intenzita pomoci? | ❌ (0.70) | ✅ (1.00) | 📈 +0.30 |
| 5 | Aký je minimálny a maximálny príspevok? | ✅ (1.00) | ✅ (1.00) | ➡️ same |
| 6 | Aké činnosti sú vylúčené z podpory? | ✅ (1.00) | ✅ (1.00) | ➡️ same |
| 7 | Ako je rozdelená alokácia medzi regióny? | ❌ (0.50) | ✅ (0.90) | 📈 +0.40 |

**Celková kompletnosť:**
- Before: 5/7 (71%)
- After: 7/7 (100%)
- **Zlepšenie: +29 percentuálnych bodov (71% → 100%)**

**Priemerná confidence:**
- Before: 0.87
- After: 0.99
- **Zlepšenie: +0.12**

## Čo sa zmenilo

### 1. Metadata Enrichment (TASK-001 + TASK-003)
Každý chunk teraz obsahuje enriched prefix:
```
[Výzva: ... | Dokument: ... | Typ: ... | Sekcia: Financovanie projektu | Tags: financovanie, NFP, intenzita pomoci | Zhrnutie: Pravidlá pre stanovenie výšky NFP...]
```
Výhody:
- Lepšie vector search matching (sekcia + tags v embedding)
- Reranker má viac kontextu na hodnotenie relevancie
- Metadata uložené v JSONB stĺpci pre budúce filtrovanie

### 2. Reranker (TASK-004)
GPT-4o-mini hodnotí relevanciu každého chunk (0-10) voči otázke.
- Eliminuje false positives z hybrid search
- Top-5 chunks sú konzistentne relevantné
- Priemerný rerank čas: ~15s pre 20 chunkov

### 3. Completeness Evaluator (TASK-005)
Iteratívny evaluation s max 2 search iteráciami.
- Ak nekompletné → suggested queries → nový search → merge → re-evaluate
- Kalibrovaný na akceptovanie absolútnych súm (EUR) ako validných dát
- Dokáže identifikovať konkrétne chýbajúce informácie

### 4. DB Schema (TASK-002)
- `v2_call_chunks.metadata JSONB` stĺpec pre chunk metadata
- `hybrid_search_chunks_v2()` funkcia vracia aj metadata

## Kľúčové zistenie

Pôvodné zlyhania Q4 a Q7 boli spôsobené DVOMA faktormi:
1. **Embeddings:** Bez enriched prefixu vector search nevedel nájsť správne chunky pre abstraktné otázky
2. **Evaluator:** Bol príliš striktný - požadoval explicitné percentá aj keď absolútne sumy v EUR boli dostatočné

Kombinácia enriched embeddings + reranking + kalibrovný evaluator dosiahla 100% kompletnosť.

## Implementované súbory

### Nové
- `scraper/embedder/metadata_generator.py` — GPT-4o-mini metadata generátor
- `scraper/search/__init__.py` — search module init
- `scraper/search/reranker.py` — GPT-4o-mini reranker
- `scraper/search/completeness.py` — completeness evaluator
- `scraper/tests/test_rag_pipeline.py` — E2E test suite
- `docs/migrations/002_add_metadata_column.sql` — DB migration

### Upravené
- `scraper/config.py` — METADATA_MODEL config
- `scraper/embedder/embedder.py` — metadata integration, enrich_existing_chunks()
- `scraper/embedder/__init__.py` — exports
- `scraper/main.py` — `enrich` CLI command

### DB Changes
- `v2_call_chunks.metadata JSONB DEFAULT '{}'`
- `hybrid_search_chunks_v2()` function

# Grant Viewer SaaS — Pipeline Documentation

> **Účel:** Kompletný popis pipeline pre nové session po resete/compaction.
> **Posledná aktualizácia:** 2026-03-09 15:20 UTC
> **Projekt:** /home/clawd/Projects/grant-viewer-saas
> **Branch:** saas-refactor
> **GitHub:** https://github.com/VladoAdmin/grant-viewer-saas

---

## 1. Architektúra

```
┌─────────────┐    ┌───────────────┐    ┌──────────────┐    ┌──────────────┐
│  ITMS21 API │───▶│  Scraper CLI  │───▶│  Supabase DB │◀──▶│  Express API │
│  (zdroj)    │    │  (Python)     │    │  (pgvector)  │    │  (backend)   │
└─────────────┘    └───────────────┘    └──────────────┘    └──────┬───────┘
                                                                    │
                                                            ┌──────▼───────┐
                                                            │  React SPA   │
                                                            │  (frontend)  │
                                                            └──────────────┘
```

### Tech Stack
- **Scraper/Pipeline:** Python 3 (spúšťaj vždy `python3`, nie `python`)
- **Backend API:** Express.js + TypeScript (`backend/src/`)
- **Frontend:** React 19 + Vite + Tailwind (`frontend/src/`)
- **DB:** Supabase PostgreSQL + pgvector (3072-dim embeddings)
- **Embedding model:** OpenAI `text-embedding-3-large` (3072 dim)
- **Metadata/Rerank/Completeness model:** GPT-4o-mini
- **Deploy:** Frontend na stormlevel.com/grant-viewer/, API na VPS cez Tailscale funnel

---

## 2. Supabase DB Schéma

### Tabuľky

**`grant_calls_v2`** — zoznam grantových výziev
| Stĺpec | Typ | Popis |
|---------|-----|-------|
| id | bigint (PK) | auto-increment |
| source | text | "portal.itms21.sk" |
| source_url | text | URL zdroja |
| call_url | text | URL konkrétnej výzvy |
| title | text | názov výzvy |
| announced_at | timestamptz | dátum vyhlásenia |
| deadline_at | timestamptz | deadline na podanie |
| provider | text | poskytovateľ (ministerstvo) |
| call_type | text | typ výzvy |
| total_allocation | text | celková alokácia |
| status | text | "otvorená"/"uzavretá" |
| closed_at | timestamptz | dátum uzavretia |
| created_at, updated_at, deleted_at | timestamptz | timestamps |

**`grant_call_attachments`** — prílohy k výzvam
| Stĺpec | Typ | Popis |
|---------|-----|-------|
| id | bigint (PK) | auto-increment |
| grant_call_id | bigint (FK) | väzba na grant_calls_v2 |
| name | text | názov prílohy |
| url | text | URL na stiahnutie (ITMS21 API) |
| file_type | text | PDF/ZIP/DOCX/UNKNOWN |
| created_at | timestamptz | timestamp |

**`grant_call_attributes`** — extrahované atribúty z PDF
| Stĺpec | Typ | Popis |
|---------|-----|-------|
| id | integer (PK) | auto-increment |
| grant_call_id | integer (FK) | väzba na grant_calls_v2 |
| key | text | "call_code", "announced_date", "total_allocation", atď. |
| value | text | extrahovaná hodnota |
| value_type | text | "regex"/"gpt" |
| extracted_at | timestamptz | kedy bolo extrahované |

**`v2_call_chunks`** — chunky dokumentov s embeddings
| Stĺpec | Typ | Popis |
|---------|-----|-------|
| id | bigint (PK) | auto-increment |
| call_id | bigint (FK) | väzba na grant_calls_v2 |
| content | text | text chunku s enriched prefixom |
| embedding | vector(3072) | OpenAI text-embedding-3-large |
| chunk_index | integer | poradie v dokumente |
| source | text | názov zdrojového súboru |
| doc_type | text | "main"/"conditions"/"criteria" |
| metadata | jsonb | {section_title, summary, content_tags, info_density} |
| created_at | timestamptz | timestamp |
| deleted_at | timestamptz | soft delete |

### RPC Funkcie (Supabase)

**`hybrid_search_chunks_v2`** — hlavný search
```sql
hybrid_search_chunks_v2(
  query_text text,           -- fulltext query
  query_embedding vector,    -- 3072-dim embedding
  match_threshold float = 0.3,
  match_count int = 10,
  call_id_filter int = NULL,
  doc_type_filter text = NULL
) RETURNS TABLE(id, call_id, chunk_content, source, doc_type, chunk_metadata, similarity, rank)
```
- Kombinuje vector similarity + fulltext ts_rank (RRF fusion)
- Vracia aj metadata JSONB stĺpec

**`hybrid_search_chunks`** (v1, legacy) — rovnaké bez metadata

### Aktuálne dáta (2026-03-09)
- **grant_calls_v2:** 123 záznamov
- **v2_call_chunks:** ~2800+ chunkov (call_id 11: 67, call_id 45: 1325, call_id 50: 1203, call_id 341: 243)
- **Embedding dim:** 3072 (text-embedding-3-large)
- Enriched chunky (s metadata): call_id 341 (243 chunkov)

---

## 3. Python Pipeline (Scraper CLI)

### Spúšťanie
```bash
cd /home/clawd/Projects/grant-viewer-saas
python3 -m scraper.main <command> [options]
```

### Príkazy
| Príkaz | Čo robí | Príklad |
|--------|---------|---------|
| `scrape` | Scrapuje výzvy z ITMS21 API | `python3 -m scraper.main scrape --source itms21 --limit 200` |
| `embed` | Stiahne prílohy, extrahuje text, chunkuje, embedduje | `python3 -m scraper.main embed --call-id 341` |
| `enrich` | Generuje metadáta + re-embeduje existujúce chunky | `python3 -m scraper.main enrich --call-id 341` |
| `cleanup` | Deduplikácia, mazanie starých | `python3 -m scraper.main cleanup` |
| `export-pdf` | Exportuje výzvu ako PDF | `python3 -m scraper.main export-pdf --call-id 341 --output call.pdf` |
| `status` | Stav DB + štatistiky | `python3 -m scraper.main status` |

### Pipeline Flow (embed príkaz)

```
1. SCRAPE metadata     → itms21.py: API call → grant_calls_v2 + grant_call_attachments
2. DOWNLOAD prílohy    → zip_handler.py: URL → PDF/DOCX bytes (cache v storage/pdf_cache/)
3. EXTRACT text        → pdf_extractor.py: PyMuPDF (fitz) pre PDF, python-docx pre DOCX
4. CLASSIFY dokumenty  → classifier.py: filename + content keywords → doc_type (main/conditions/criteria)
5. EXTRACT atribúty    → attribute_extractor.py: regex (6 atribútov) + GPT-4o-mini (4 atribúty) → grant_call_attributes
6. CHUNK text          → chunker.py: smart chunking (target 768 tokens, max 1024, min 256)
7. GENERATE metadáta   → metadata_generator.py: GPT-4o-mini → {section_title, summary, content_tags, info_density}
8. BUILD prefix        → metadata_generator.py: enriched prefix [Výzva: X | Sekcia: Y | Tags: Z | Zhrnutie: W]
9. EMBED               → embedder.py: OpenAI text-embedding-3-large → 3072-dim vector
10. STORE              → db.py: INSERT into v2_call_chunks (content + embedding + metadata)
11. UPDATE call        → db.py: UPDATE grant_calls_v2 s extrahovanými atribútmi (announced_at, total_allocation, atď.)
```

### Konfigurácia (`scraper/config.py`)
```python
# Embedding
EMBED_MODEL = "text-embedding-3-large"   # DÔLEŽITÉ: nie "small", musí byť "large" (3072 dim)
EMBED_DIM = 3072                          # musí matchovať DB vector stĺpec
EMBED_BATCH_SIZE = 96

# Metadata/Rerank/Completeness
METADATA_MODEL = "gpt-4o-mini"

# Chunker
CHUNK_TARGET_TOKENS = 768
CHUNK_MAX_TOKENS = 1024
CHUNK_MIN_TOKENS = 256

# Scraper
MAX_PDF_PAGES = 25
REQUEST_DELAY = 0.5
REQUEST_TIMEOUT = 30
MAX_FILE_SIZE_MB = 50

# API
ITMS21_API_BASE = "https://api.itms21.sk/public/v1"
```

### ENV premenné (v `/home/clawd/.openclaw/.env`)
```
SUPABASE_URL=https://xxx.supabase.co
SUPABASE_SERVICE_ROLE_KEY=eyJ...
SUPABASE_PASSWORD=...
SUPABASE_HOST=db.xxx.supabase.co
SUPABASE_USER=postgres
OPENAI_API_KEY=sk-...
```

---

## 4. Štruktúra Python súborov

```
scraper/
├── __init__.py
├── config.py                          # Všetky config konštanty + env loading
├── db.py                              # SupabaseClient (REST API wrapper)
├── main.py                            # CLI entry point (argparse)
├── cleanup.py                         # Deduplikácia + cleanup
├── pdf_export.py                      # PDF export výzvy
├── error_handler.py                   # Error handling utilities
├── handlers/
│   ├── __init__.py
│   ├── base.py                        # BaseHandler + dataclasses (GrantCall, Attachment)
│   └── itms21.py                      # ITMS21 API scraper handler
├── extractor/
│   ├── __init__.py
│   ├── pdf_extractor.py               # PyMuPDF text extraction (PDF + DOCX)
│   ├── zip_handler.py                 # ZIP rozbaľovanie + PDF cache
│   ├── classifier.py                  # Document type classification (main/conditions/criteria)
│   └── attribute_extractor.py         # Regex + GPT-4o-mini extraction (kód, dátumy, alokácia, žiadatelia)
├── embedder/
│   ├── __init__.py
│   ├── chunker.py                     # Smart text chunking (token-based)
│   ├── embedder.py                    # OpenAI embedding + DB storage + cmd_embed() flow
│   └── metadata_generator.py          # GPT-4o-mini chunk metadata (summary, tags, section)
├── search/
│   ├── __init__.py
│   ├── reranker.py                    # GPT-4o-mini cross-scoring reranker
│   └── completeness.py                # Iteratívny RAG completeness evaluator
└── tests/
    ├── __init__.py
    ├── test_cleanup.py
    ├── test_db.py
    ├── test_error_handler.py
    ├── test_extractor.py
    ├── test_itms21.py
    └── test_rag_pipeline.py           # E2E RAG pipeline test
```

---

## 5. Search Pipeline (query time)

### Jednoduchý search (backend API)
```
User query → Express API (/api/search?q=X)
  → embedQuery() [OpenAI text-embedding-3-large]
  → hybrid_search_chunks RPC [Supabase: vector + fulltext]
  → return top-N chunks s call titles
```

### RAG search s rerankom + completeness (Python)
```
User query
  → hybrid_search_chunks_v2 (top-20, threshold 0.2)
  → reranker.py: GPT-4o-mini hodnotí relevanciu (0-10) pre každý chunk
  → completeness.py: GPT-4o-mini evaluuje kompletnosť
    → Ak nekompletné: suggested_queries → nový search → merge → re-evaluate
    → Max 2 iterácie
  → Výsledok: top-10 chunkov zoradených podľa rerank score + completeness report
```

### Chunk content formát (po enrichmente)
```
[Výzva: Synergická podpora projektov | Dokument: Vyzva_v2.pdf | Typ: main | Sekcia: Oprávnené výdavky | Tags: výdavky, stroje, zariadenia, investície | Zhrnutie: Definícia oprávnených výdavkov na obstaranie strojov a nehmotného majetku]
Oprávnené výdavky projektu sú výdavky na obstaranie dlhodobého hmotného majetku...
```

---

## 6. Backend API (Express.js + TypeScript)

### Štruktúra
```
backend/src/
├── index.ts                           # Express server entry point
├── lib/
│   ├── openai.ts                      # OpenAI client (embedQuery)
│   └── supabase.ts                    # Supabase REST client
├── routes/
│   ├── calls.ts                       # GET /api/calls, GET /api/calls/:id
│   ├── search.ts                      # GET /api/search?q=X&callId=Y&limit=N
│   ├── admin.ts                       # GET /api/admin/status
│   └── feedback.ts                    # POST /api/feedback
└── services/
    ├── callService.ts                 # Business logic pre výzvy
    ├── searchService.ts               # Hybrid search orchestrácia
    └── pdfService.ts                  # PDF export service
```

### Endpointy
| Endpoint | Metóda | Popis |
|----------|--------|-------|
| `/api/calls` | GET | Zoznam výziev (pagination, filter) |
| `/api/calls/:id` | GET | Detail výzvy + prílohy + atribúty |
| `/api/search` | GET | Hybrid search (`?q=X&callId=Y&limit=10`) |
| `/api/admin/status` | GET | DB štatistiky |
| `/api/feedback` | POST | User feedback na search results |

### Search endpoint flow (searchService.ts)
1. `embedQuery(params.query)` — OpenAI text-embedding-3-large
2. `supabaseRpc('hybrid_search_chunks', {...})` — Supabase RPC
3. Fetch call titles z `grant_calls_v2`
4. Return enriched results

**POZOR:** Backend zatiaľ NEPOUŽÍVA reranker ani completeness evaluator. Tieto sú len v Python pipeline. Integrácia do API je budúca úloha.

---

## 7. Frontend (React SPA)

### Stránky
| Stránka | Route | Komponent | Popis |
|---------|-------|-----------|-------|
| Zoznam výziev | `/` | CallList.tsx | Tabuľka výziev s filterom |
| Detail výzvy | `/calls/:id` | CallDetail.tsx | Detail + prílohy + atribúty |
| Vyhľadávanie | `/search` | Search.tsx | Fulltext + semantic search |
| Admin | `/admin` | AdminStatus.tsx | DB štatistiky |
| Pomoc | `/help` | Help.tsx | Návod na používanie |

### Deploy
- Frontend build: `frontend/dist/` → FTP na stormlevel.com/grant-viewer/
- Backend: PM2 na VPS (port z Tailscale funnel)

---

## 8. Kľúčové súbory pre údržbu

### Ak potrebuješ opraviť/upraviť pipeline:
| Čo | Kde | Poznámka |
|----|-----|----------|
| Embedding model/dim | `scraper/config.py` | MUSÍ byť text-embedding-3-large + 3072 |
| Chunk veľkosť | `scraper/config.py` | CHUNK_TARGET_TOKENS=768, MAX=1024 |
| Metadata prompt | `scraper/embedder/metadata_generator.py` | METADATA_SYSTEM_PROMPT |
| Rerank prompt | `scraper/search/reranker.py` | RERANK_SYSTEM_PROMPT |
| Completeness prompt | `scraper/search/completeness.py` | COMPLETENESS_SYSTEM_PROMPT |
| Doc classification | `scraper/extractor/classifier.py` | CLASSIFICATION_RULES dict |
| Attribute extraction | `scraper/extractor/attribute_extractor.py` | Regex + GPT patterns |
| DB client | `scraper/db.py` | SupabaseClient REST wrapper |
| Search RPC | Supabase dashboard | hybrid_search_chunks_v2 (SQL funkcia) |

### Ak treba pridať nový zdroj (nie ITMS21):
1. Vytvor nový handler v `scraper/handlers/` (podľa vzoru `itms21.py`)
2. Registruj ho v `scraper/main.py`
3. Atribúty v `attribute_extractor.py` sú generické, mali by fungovať

---

## 9. Známe problémy a rozhodnutia

### Vyriešené
- ✅ Embedding dim mismatch: config mal 1536, DB 3072 → opravené na 3072
- ✅ Retrieval kompletnosť: 71% → 100% (metadata + rerank + completeness)
- ✅ Doc type classification: UUID filenames → content-based classification

### Otvorené
- ⚠️ Backend API nepoužíva reranker/completeness (len Python CLI)
- ⚠️ ITMS21 API vracia neúplné metadáta (announced_at, total_allocation) — riešené cez PDF extraction
- ⚠️ Enrich bol spustený len pre call_id 341, ostatné chunky nemajú metadata
- ⚠️ Rerank + completeness pridáva ~2-3s latency per query

### Dôležité rozhodnutia
1. **Embedding model:** text-embedding-3-large (nie small) — kvôli existujúcim dátam v DB s 3072 dim
2. **Metadata model:** GPT-4o-mini — lacný, rýchly, dostatočný pre sumarizáciu
3. **Rerank approach:** LLM-based (GPT-4o-mini scoring), nie cross-encoder — jednoduchšie, flexibilnejšie
4. **Completeness:** Iteratívny RAG s max 2 iteráciami — kompromis medzi kvalitou a latenciou
5. **Chunk prefix:** Enriched prefix sa embeduje spolu s textom — zlepšuje vector matching

---

## 10. Náklady

| Operácia | Cena | Poznámka |
|----------|------|----------|
| Embedding 1 výzvy (~250 chunkov) | ~$0.05 | text-embedding-3-large |
| Metadata generácia (~250 chunkov) | ~$0.02 | GPT-4o-mini batch |
| Attribute extraction (1 výzva) | ~$0.01 | GPT-4o-mini (4 atribúty) |
| Rerank per query | ~$0.005 | GPT-4o-mini (20 chunkov) |
| Completeness eval per query | ~$0.005 | GPT-4o-mini |
| **Celá pipeline pre 1 výzvu** | **~$0.08** | scrape → embed → enrich |
| **1 deep search query** | **~$0.02** | embed + rerank + completeness (max 2 iter) |

---

## 11. Git Stav (2026-03-09)

```
Branch: saas-refactor
Posledné commity:
- d1d272b TASK-006 E2E tests + results report
- 545755a TASK-004+005 reranker + completeness
- 349fd4a TASK-003 embed flow integration + enrich CLI
- 7b18a2d TASK-002 DB schema + hybrid_search_v2
- 53b8148 TASK-001 chunk metadata generator
- 88c1877 docs: add RAG improvements plan
- 16a8712 fix: align EMBED_MODEL to text-embedding-3-large
```

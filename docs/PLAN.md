# Plan: Grant Viewer SaaS — Phase 1 MVP

## Cieľ

Postaviť funkčné MVP za 2 týždne: scraping 3 zdrojov (ITMS21, APA/ISPP, SIEA), PDF extraction + chunking + embedding do vektorovej DB, hybrid search, a web app so zoznamom výziev + kontextovým vyhľadávaním.

## Kontext

- **PRD:** docs/PRD.md
- **Fáza:** Phase 1 MVP (Week 1-2)
- **Predchádzajúce:** Greenfield projekt, iba PRD existuje
- **Tech stack:** Python scrapers, Express.js + TypeScript backend, React frontend, Supabase (PostgreSQL + pgvector)

## Reference Docs

- [Supabase pgvector docs](https://supabase.com/docs/guides/ai/vector-columns)
- [OpenAI Embeddings API](https://platform.openai.com/docs/guides/embeddings)
- [PyMuPDF (fitz) docs](https://pymupdf.readthedocs.io/)
- [python-docx docs](https://python-docx.readthedocs.io/)
- [ITMS21 portal](https://portal.itms21.sk/vyhlasene-vyzvy/) — pozor: server-rendered, vyžaduje headless browser alebo API reverse engineering
- [APA výzvy](https://www.apa.sk/aktualne-vyzvy) — klasický HTML, BeautifulSoup friendly
- [SIEA výzvy](https://www.siea.sk/strukturalne-fondy-eu/program-slovensko/vyzvy-implementovane-siea/)

## Architektúra (Phase 1)

```
grant-viewer-saas/
├── docs/                     # PRD, PLAN, LESSONS
├── scraper/                  # Python scraping + extraction
│   ├── handlers/             # Per-source handlers
│   │   ├── base.py           # Abstract base handler
│   │   ├── itms21.py         # ITMS21 handler
│   │   ├── apa.py            # APA/ISPP handler
│   │   └── siea.py           # SIEA handler
│   ├── extractor/            # PDF/ZIP/DOCX extraction
│   │   ├── pdf_extractor.py
│   │   ├── zip_handler.py
│   │   └── classifier.py     # Rule-based doc classification
│   ├── embedder/             # Chunking + embedding
│   │   ├── chunker.py
│   │   └── embedder.py
│   ├── db.py                 # Supabase client
│   ├── config.py             # Settings, env vars
│   ├── main.py               # CLI entry point
│   └── requirements.txt
├── backend/                  # Express.js API
│   ├── src/
│   │   ├── index.ts
│   │   ├── routes/
│   │   │   ├── calls.ts
│   │   │   ├── search.ts
│   │   │   └── admin.ts
│   │   ├── services/
│   │   │   ├── searchService.ts
│   │   │   └── callService.ts
│   │   └── lib/
│   │       ├── supabase.ts
│   │       └── openai.ts
│   ├── package.json
│   └── tsconfig.json
├── frontend/                 # React app
│   ├── src/
│   │   ├── App.tsx
│   │   ├── pages/
│   │   │   ├── CallList.tsx
│   │   │   ├── CallDetail.tsx
│   │   │   ├── Search.tsx
│   │   │   └── AdminStatus.tsx
│   │   ├── components/
│   │   │   ├── CallCard.tsx
│   │   │   ├── SearchBox.tsx
│   │   │   ├── FilterBar.tsx
│   │   │   └── ChunkResult.tsx
│   │   ├── hooks/
│   │   │   └── useApi.ts
│   │   └── lib/
│   │       └── api.ts
│   ├── package.json
│   └── tailwind.config.js
└── supabase/
    └── migrations/
        └── 001_initial_schema.sql
```

---

## Task List

### Week 1: Backend + Scraping Pipeline

| ID | Task | Estimate | Dependencies | Priority |
|----|------|----------|--------------|----------|
| TASK-001 | Supabase schema + migrácie | 3h | — | P0 |
| TASK-002 | Python scraper framework (base handler, config, DB client) | 4h | TASK-001 | P0 |
| TASK-003 | ITMS21 handler | 5h | TASK-002 | P0 |
| TASK-004 | APA handler | 4h | TASK-002 | P0 |
| TASK-005 | SIEA handler | 4h | TASK-002 | P0 |
| TASK-006 | ZIP/PDF extractor (PyMuPDF) | 4h | TASK-002 | P0 |
| TASK-007 | Rule-based document classifier | 3h | TASK-006 | P0 |
| TASK-008 | Chunker (400 tokens, 50 overlap, context prefix) | 3h | TASK-006 | P0 |
| TASK-009 | Embedder (OpenAI text-embedding-3-large) | 3h | TASK-008 | P0 |
| TASK-010 | Hybrid search RPC function (vector + fulltext + RRF) | 3h | TASK-001, TASK-009 | P0 |

### Week 2: API + Frontend

| ID | Task | Estimate | Dependencies | Priority |
|----|------|----------|--------------|----------|
| TASK-011 | Express.js API setup (TypeScript, CORS, error handling) | 2h | TASK-001 | P0 |
| TASK-012 | API: GET /api/calls (list + filters) | 2h | TASK-011 | P0 |
| TASK-013 | API: GET /api/calls/:id (detail + attributes) | 2h | TASK-012 | P0 |
| TASK-014 | API: POST /api/search (hybrid search) | 3h | TASK-010, TASK-011 | P0 |
| TASK-015 | API: GET /api/admin/status + POST /api/admin/trigger | 2h | TASK-011 | P0 |
| TASK-016 | React app setup (Vite + Tailwind + React Router) | 2h | — | P0 |
| TASK-017 | CallList page (zoznam výziev + filtrovanie) | 4h | TASK-012, TASK-016 | P0 |
| TASK-018 | CallDetail page (detail výzvy + atribúty) | 3h | TASK-013, TASK-016 | P0 |
| TASK-019 | Search page (kontextové vyhľadávanie) | 4h | TASK-014, TASK-016 | P0 |
| TASK-020 | AdminStatus page (scraper status, manual trigger) | 2h | TASK-015, TASK-016 | P1 |
| TASK-021 | End-to-end integration test (scrape → embed → search → display) | 3h | ALL | P0 |
| TASK-022 | Deploy (Vercel frontend, VPS backend, Supabase DB) | 3h | ALL | P0 |

**Total estimate: 63 hodín (~8 pracovných dní)**

---

## Detaily implementácie

### TASK-001: Supabase schema + migrácie

- **Čo:** Vytvoriť DB schému podľa PRD sekcie 7, vrátane pgvector extension, indexov, RPC funkcie
- **Kde:** `supabase/migrations/001_initial_schema.sql`
- **Súbory:** `supabase/migrations/001_initial_schema.sql`
- **Detaily:**
  - `CREATE EXTENSION IF NOT EXISTS vector;`
  - Tabuľky: `grant_calls_v2`, `grant_call_attachments`, `doc_classification`, `v2_call_chunks`, `grant_call_attributes`
  - GIN index na `v2_call_chunks.content` pre fulltext
  - IVFFlat index na `v2_call_chunks.embedding` pre vector search (HNSW ak Supabase podporuje)
  - `hybrid_search_chunks` RPC funkcia podľa PRD
  - Pridať `scraper_runs` tabuľku pre admin status tracking:
    ```sql
    CREATE TABLE scraper_runs (
        id SERIAL PRIMARY KEY,
        source TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'running', -- running, success, error
        started_at TIMESTAMPTZ DEFAULT NOW(),
        finished_at TIMESTAMPTZ,
        calls_found INT DEFAULT 0,
        calls_new INT DEFAULT 0,
        error_message TEXT
    );
    ```
- **Validácia:** SQL migrácia prejde bez chýb, tabuľky existujú v Supabase

### TASK-002: Python scraper framework

- **Čo:** Základná štruktúra Python projektu, base handler interface, Supabase klient, config
- **Kde:** `scraper/`
- **Súbory:**
  - `scraper/config.py` — env vars (SUPABASE_URL, SUPABASE_KEY, OPENAI_API_KEY, STORAGE_PATH)
  - `scraper/db.py` — Supabase client wrapper (upsert calls, save attachments, insert chunks)
  - `scraper/handlers/base.py` — AbstractBaseHandler s metódami: `scrape()`, `parse_call()`, `download_attachments()`
  - `scraper/main.py` — CLI: `python main.py scrape [--source itms21|apa|siea|all]`
  - `scraper/requirements.txt` — supabase, requests, beautifulsoup4, pymupdf, python-docx, openai, tiktoken
- **Pattern:**
  ```python
  class BaseHandler(ABC):
      source_name: str
      base_url: str
      
      @abstractmethod
      def get_call_urls(self) -> List[str]: ...
      
      @abstractmethod
      def parse_call(self, url: str) -> GrantCall: ...
      
      def scrape(self) -> ScrapeResult:
          # 1. Get all call URLs
          # 2. Compare with DB (skip existing)
          # 3. Parse new calls
          # 4. Save to DB
          # 5. Download attachments
          # 6. Return stats
  ```
- **Validácia:** `python main.py --help` funguje, import base handler bez chýb

### TASK-003: ITMS21 handler

- **Čo:** Scraper pre portal.itms21.sk/vyhlasene-vyzvy/
- **Kde:** `scraper/handlers/itms21.py`
- **Detaily:**
  - ITMS21 je server-rendered stránka s filtrami. Výzvy sa zobrazujú ako paginated list.
  - **RIZIKO:** Stránka môže vyžadovať JavaScript rendering (SSR s dynamic loading). Ak requests + BS4 nestačí, fallback na Playwright.
  - Detail výzvy na `portal.itms21.sk/vyhlasena-vyzva/?id=XXXX` obsahuje: názov, kód výzvy, program, typ, dátum vyhlásenia, deadline, alokácia, oprávnení žiadatelia, prílohy (PDF/ZIP).
  - Prílohy sú priamo downloadovateľné linky na PDF/ZIP.
  - Extrahovať: title, source_url, call_url, announced_at, deadline_at, provider, call_type, total_allocation, status, prílohy.
- **Approach:**
  1. Skúsiť requests + BS4
  2. Ak 403/empty: Playwright headless
  3. Parsovať zoznam výziev, stránkovanie
  4. Pre každú novú výzvu: parse detail page
  5. Download attachments do `storage/itms21/{call_id}/`
- **Validácia:** Scraper nájde aspoň 5 otvorených výziev, uloží do DB s prílohami

### TASK-004: APA handler

- **Čo:** Scraper pre www.apa.sk/aktualne-vyzvy a www.apa.sk/projektove-podpory/spp-2023-2027-vyzvy
- **Kde:** `scraper/handlers/apa.py`
- **Detaily:**
  - APA stránka je klasický HTML, BS4 friendly
  - Výzvy sú listované na stránke ako odkazy na podstránky
  - Každá výzva má: názov, dátum, popis, prílohy (PDF, ZIP)
  - Niektoré prílohy sú ZIP s viacerými PDF vnútri
- **Approach:**
  1. GET hlavný listing page
  2. Parse výzvy z HTML (h2/h3 + links)
  3. Follow each link to detail page
  4. Extrahovať metadata + attachment URLs
  5. Download do `storage/apa/{call_id}/`
- **Validácia:** Scraper nájde aktuálne výzvy z APA, uloží metadata + prílohy

### TASK-005: SIEA handler

- **Čo:** Scraper pre www.siea.sk výzvy
- **Kde:** `scraper/handlers/siea.py`
- **Detaily:**
  - SIEA má výzvy na rôznych podstránkach (Program Slovensko, Plán obnovy)
  - Primárne: `siea.sk/strukturalne-fondy-eu/program-slovensko/vyzvy-implementovane-siea/`
  - Štruktúra: listing s kartami výziev, detail na podstránke
  - Prílohy: PDF priamo na detail stránke
- **Approach:** Rovnaký pattern ako APA (requests + BS4)
- **Validácia:** Scraper nájde aktuálne SIEA výzvy

### TASK-006: ZIP/PDF extractor

- **Čo:** Extraction pipeline: ZIP unpack, PDF text extraction (PyMuPDF), DOCX extraction
- **Kde:** `scraper/extractor/`
- **Súbory:**
  - `scraper/extractor/zip_handler.py` — rozbalí ZIP, vráti zoznam súborov s typmi
  - `scraper/extractor/pdf_extractor.py` — PyMuPDF text extraction, max 25 strán
- **Pseudocode:**
  ```python
  def extract_from_path(path: str) -> List[Document]:
      if path.endswith('.zip'):
          files = unzip(path, target_dir)
          return [extract_file(f) for f in files]
      elif path.endswith('.pdf'):
          return [extract_pdf(path)]
      elif path.endswith('.docx'):
          return [extract_docx(path)]
  
  def extract_pdf(path: str, max_pages=25) -> Document:
      doc = fitz.open(path)
      text = ""
      for page in doc[:max_pages]:
          text += page.get_text()
      return Document(name=basename(path), text=text, pages=len(doc))
  ```
- **Validácia:** Extrahovať text z 5 rôznych PDF (vrátane jedného zo ZIP), text nie je prázdny

### TASK-007: Rule-based document classifier

- **Čo:** Klasifikácia dokumentov podľa PRD Appendix B (keyword-based)
- **Kde:** `scraper/extractor/classifier.py`
- **Detaily:**
  - Vstup: názov súboru + prvých 2000 znakov textu
  - Výstup: doc_type (main, conditions, criteria, costs, skip) + confidence
  - Prvý pass: filename matching (napr. "Výzva" v názve → main)
  - Druhý pass: keyword counting v texte (podľa PRD CLASSIFICATION_RULES)
  - Confidence: pomer keyword hits k total keywords pre daný typ
  - Ak žiadny typ > threshold (0.3): default = "main" s low confidence
- **Validácia:** Klasifikácia 10 testovacích dokumentov s aspoň 80% accuracy

### TASK-008: Chunker

- **Čo:** Rozdelenie textu na chunky pre embedding
- **Kde:** `scraper/embedder/chunker.py`
- **Detaily:**
  - Target: 400 tokens, range 256-512
  - Overlap: 50 tokens
  - Split strategy: paragraphs (`\n\n`) → sentences (regex) → token boundary
  - Context prefix pre každý chunk:
    ```
    Výzva: {call_title}
    Dokument: {doc_name}
    Typ: {doc_type}
    ---
    {chunk_text}
    ```
  - Tokenizácia: tiktoken (cl100k_base pre OpenAI)
- **Pseudocode:**
  ```python
  def chunk_document(text: str, call_title: str, doc_name: str, 
                     doc_type: str, target_tokens=400, overlap=50) -> List[Chunk]:
      paragraphs = text.split('\n\n')
      chunks = []
      current = []
      current_tokens = 0
      
      for para in paragraphs:
          para_tokens = count_tokens(para)
          if current_tokens + para_tokens > target_tokens and current:
              chunk_text = '\n\n'.join(current)
              chunks.append(make_chunk(chunk_text, call_title, doc_name, doc_type))
              # Keep overlap
              overlap_text = get_last_n_tokens('\n\n'.join(current), overlap)
              current = [overlap_text]
              current_tokens = overlap
          current.append(para)
          current_tokens += para_tokens
      
      if current:
          chunks.append(make_chunk('\n\n'.join(current), call_title, doc_name, doc_type))
      
      return chunks
  ```
- **Validácia:** Chunk 10-stránkový dokument, skontrolovať: veľkosť chunkov v range, overlap existuje, context prefix je correct

### TASK-009: Embedder

- **Čo:** Embedding chunkov cez OpenAI API + uloženie do Supabase
- **Kde:** `scraper/embedder/embedder.py`
- **Detaily:**
  - Model: text-embedding-3-large (3072 dim)
  - Batch: max 2048 chunkov naraz (API limit), ale reálne po 100 pre rate limit safety
  - Uloženie: batch insert do `v2_call_chunks` cez Supabase client
  - Idempotencia: pred embedovaním výzvy zmazať existujúce chunky pre daný call_id
  - Cost control: log počet tokenov a odhadovanú cenu
- **Pseudocode:**
  ```python
  def embed_and_store(call_id: int, chunks: List[Chunk]):
      # Delete existing chunks for this call (idempotent)
      db.delete_chunks(call_id)
      
      # Batch embed
      for batch in batched(chunks, 100):
          texts = [c.full_text for c in batch]
          embeddings = openai.embeddings.create(
              model="text-embedding-3-large",
              input=texts
          )
          
          # Insert to DB
          rows = [
              {"call_id": call_id, "content": c.full_text, 
               "embedding": e.embedding, "chunk_index": i,
               "source": c.doc_name, "doc_type": c.doc_type}
              for i, (c, e) in enumerate(zip(batch, embeddings.data))
          ]
          db.insert_chunks(rows)
  ```
- **Validácia:** Embedovať 1 výzvu (5-10 chunkov), overiť vektory v DB (rozmer 3072, nie null)

### TASK-010: Hybrid search RPC function

- **Čo:** PostgreSQL RPC funkcia pre hybrid search (vector + fulltext + RRF)
- **Kde:** `supabase/migrations/001_initial_schema.sql` (súčasť migrácie)
- **Detaily:**
  - Implementovať `hybrid_search_chunks()` podľa PRD sekcie 7.2
  - Vector: cosine similarity cez pgvector `<=>` operátor
  - Fulltext: `to_tsvector('simple', content) @@ plainto_tsquery('simple', query)`
  - RRF fusion: `1/(k + rank)` kde k=60 (štandard)
  - Filtre: call_id (optional), doc_type (optional)
  - Threshold: 0.3 pre vector similarity
- **Validácia:** Zavolať RPC z Python/curl, skontrolovať výsledky pre known query

### TASK-011: Express.js API setup

- **Čo:** Základný Express.js server s TypeScript
- **Kde:** `backend/`
- **Súbory:**
  - `backend/src/index.ts` — server, middleware (CORS, JSON, error handler)
  - `backend/src/lib/supabase.ts` — Supabase client init
  - `backend/src/lib/openai.ts` — OpenAI client (pre search embedding)
  - `backend/package.json`, `backend/tsconfig.json`
- **Detaily:**
  - Port: 3001 (configurable via PORT env)
  - CORS: allow frontend origin
  - Error handling middleware: catch all, return JSON {error, message}
  - Health endpoint: GET /api/health
- **Validácia:** `npm run dev` spustí server, `curl localhost:3001/api/health` vráti 200

### TASK-012: API GET /api/calls

- **Čo:** List výziev s filtrovaním a stránkovaním
- **Kde:** `backend/src/routes/calls.ts`, `backend/src/services/callService.ts`
- **Detaily:**
  - Query params: `source`, `status`, `deadline_after`, `deadline_before`, `page`, `limit`
  - Default: status="Otvorená", limit=20, order by deadline_at ASC
  - Response: `{ data: GrantCall[], total: number, page: number }`
  - Joinovať `grant_call_attributes` pre enrich
- **Validácia:** curl s filtrami vráti správne výsledky

### TASK-013: API GET /api/calls/:id

- **Čo:** Detail výzvy s atribútmi a attachment listom
- **Kde:** `backend/src/routes/calls.ts`
- **Detaily:**
  - Response: `{ call: GrantCall, attributes: {key: value}[], attachments: Attachment[] }`
  - Join cez grant_call_attributes + grant_call_attachments
- **Validácia:** curl pre existujúce call_id vráti kompletné dáta

### TASK-014: API POST /api/search

- **Čo:** Hybrid search endpoint
- **Kde:** `backend/src/routes/search.ts`, `backend/src/services/searchService.ts`
- **Detaily:**
  - Body: `{ query: string, call_id?: number, doc_type?: string, limit?: number }`
  - Postup: 
    1. Embedovať query cez OpenAI
    2. Zavolať `hybrid_search_chunks` RPC
    3. Enrichovať výsledky o call title + metadata
  - Response: `{ results: SearchResult[], query: string, took_ms: number }`
  - SearchResult: `{ chunk_content, call_id, call_title, source, doc_type, similarity, rank }`
- **Validácia:** POST search s query "kto môže žiadať" vráti relevantné chunky

### TASK-015: API admin endpoints

- **Čo:** Status a manual trigger pre scraper
- **Kde:** `backend/src/routes/admin.ts`
- **Detaily:**
  - `GET /api/admin/status` — posledný run pre každý zdroj z `scraper_runs` tabuľky
  - `POST /api/admin/trigger` — body: `{source: "itms21"|"apa"|"siea"|"all"}`, spustí scraper subprocess
  - Trigger: `child_process.exec('python scraper/main.py scrape --source ${source}')`, async
- **Validácia:** Status vráti posledné runs, trigger spustí scraper

### TASK-016: React app setup

- **Čo:** React + Vite + Tailwind + React Router
- **Kde:** `frontend/`
- **Detaily:**
  - Vite + React + TypeScript
  - Tailwind CSS 3
  - React Router v6 (routes: /, /call/:id, /search, /admin)
  - Layout: header (nav), main content, footer
  - API client: `frontend/src/lib/api.ts` (fetch wrapper, base URL from env)
- **Validácia:** `npm run dev` zobrazí prázdnu stránku s navigáciou

### TASK-017: CallList page

- **Čo:** Zoznam otvorených výziev s kartami
- **Kde:** `frontend/src/pages/CallList.tsx`, `frontend/src/components/CallCard.tsx`, `frontend/src/components/FilterBar.tsx`
- **Detaily:**
  - CallCard: title, source badge, deadline, alokácia, status
  - FilterBar: dropdown source, date range pre deadline, search input (basic text filter)
  - Pagination: load more button
  - Responsive: 1 column mobile, 2-3 columns desktop
  - Loading skeleton, error state, empty state
- **Validácia:** Stránka zobrazí výzvy z DB, filtre fungujú, mobile responsive

### TASK-018: CallDetail page

- **Čo:** Detail výzvy s extrahovanými atribútmi
- **Kde:** `frontend/src/pages/CallDetail.tsx`
- **Detaily:**
  - Header: title, source, status badge
  - Metadata: deadline, alokácia, provider, typ výzvy
  - Atribúty: key-value pairs (oprávnení žiadatelia, účel, podmienky)
  - Attachments: list s download linkami
  - Back button
- **Validácia:** Detail stránka zobrazí všetky informácie pre konkrétnu výzvu

### TASK-019: Search page

- **Čo:** Kontextové vyhľadávanie s natural language query
- **Kde:** `frontend/src/pages/Search.tsx`, `frontend/src/components/SearchBox.tsx`, `frontend/src/components/ChunkResult.tsx`
- **Detaily:**
  - SearchBox: textarea + submit, príklady queries ("kto môže žiadať o dotáciu na energetiku", "podmienky pre neziskové organizácie")
  - ChunkResult: highlighted content, source doc, call title, similarity score, link to call detail
  - Loading state s "Hľadám..." indikátorom
  - Debounce: 300ms (ale search len na submit, nie live)
- **Validácia:** Search "oprávnení žiadatelia" vráti relevantné chunky z rôznych výziev

### TASK-020: AdminStatus page

- **Čo:** Dashboard pre admin operácie
- **Kde:** `frontend/src/pages/AdminStatus.tsx`
- **Detaily:**
  - Tabuľka: zdroj, posledný run, status, počet výziev, počet nových
  - Trigger button pre každý zdroj + "Scrape All"
  - Štatistiky: total výziev, total chunkov, posledný update
- **Validácia:** Admin stránka zobrazí reálne dáta, trigger button spustí scraping

### TASK-021: End-to-end integration test

- **Čo:** Overenie celého pipeline: scrape → extract → chunk → embed → search → display
- **Kde:** Manuálny test + dokumentácia v `docs/VALIDATION.md`
- **Detaily:**
  1. Spustiť scraper pre 1 zdroj (APA, najjednoduchší)
  2. Overiť dáta v DB (grant_calls_v2, attachments)
  3. Overiť extraction + chunking (v2_call_chunks populated)
  4. Overiť search cez API (POST /api/search)
  5. Overiť web app (výzva sa zobrazí v liste, detail funguje, search vráti výsledky)
  6. Spustiť pre všetky 3 zdroje
  7. Dokumentovať výsledky + screenshots
- **Validácia:** Celý pipeline funguje end-to-end, search vracia relevantné výsledky

### TASK-022: Deploy

- **Čo:** Nasadenie na produkciu
- **Kde:** Config files, CI/CD
- **Detaily:**
  - Frontend: Vercel (connect git repo, auto-deploy)
  - Backend: VPS (PM2 / systemd service)
  - Scraper: VPS (cron job alebo n8n trigger)
  - Supabase: cloud (už existuje)
  - Env vars: SUPABASE_URL, SUPABASE_KEY, OPENAI_API_KEY, CORS_ORIGIN
  - Domain: grant-viewer.stormlevel.sk (ak dostupná) alebo Vercel subdomain
- **Validácia:** Produkčná URL funguje, search vracia výsledky, scraper beží na cron

---

## Integration Points

### DB
- **Migrácie:** `supabase/migrations/001_initial_schema.sql`
- **Indexy:** GIN fulltext, IVFFlat/HNSW vector, B-tree na call_id + source
- **RPC:** `hybrid_search_chunks` funkcia

### Config (env vars)
- `SUPABASE_URL` — Supabase project URL
- `SUPABASE_ANON_KEY` — Supabase anon key (frontend)
- `SUPABASE_SERVICE_KEY` — Supabase service key (backend + scraper)
- `OPENAI_API_KEY` — pre embedding a search
- `VITE_API_URL` — backend URL pre frontend
- `PORT` — backend port (default 3001)
- `STORAGE_PATH` — lokálny path pre PDF cache (default `./storage`)

### Routes (API)
- `GET /api/health` — health check
- `GET /api/calls` — list výziev (filtrovanie, stránkovanie)
- `GET /api/calls/:id` — detail výzvy
- `POST /api/search` — hybrid search
- `GET /api/admin/status` — stav scraperov
- `POST /api/admin/trigger` — manuálny trigger

---

## Validation Strategy

### Unit testy
- **Chunker:** chunk size v range (256-512 tokens), overlap correct, context prefix present
- **Classifier:** keyword matching accuracy, edge cases (empty text, short docs)
- **DB client:** upsert idempotencia (run 2x, no duplicates)

### Integration testy
- **Scraper → DB:** scrape 1 zdroj, verify data in grant_calls_v2
- **Extractor → Chunker → Embedder:** process 1 PDF, verify chunks in v2_call_chunks (content not empty, embedding dimension 3072)
- **Search API:** POST /api/search with known query, verify relevance of top-3 results
- **Full pipeline:** scrape → extract → embed → search → return results

### E2E testy (user journeys)

- [ ] **Journey 1: Browsing výziev**
  1. Otvoriť homepage
  2. Vidieť zoznam otvorených výziev (min 5)
  3. Kliknúť na výzvu
  4. Vidieť detail s metadata + atribútmi
  5. Vidieť zoznam príloh

- [ ] **Journey 2: Kontextové vyhľadávanie**
  1. Otvoriť /search
  2. Zadať "kto môže žiadať o dotáciu na energetiku"
  3. Vidieť relevantné výsledky z SIEA/ITMS výziev
  4. Kliknúť na výsledok → presmerovanie na detail výzvy

- [ ] **Journey 3: Filtrovanie**
  1. Na homepage vybrať filter "SIEA" (zdroj)
  2. Vidieť len SIEA výzvy
  3. Zmeniť filter na "Všetky"
  4. Vidieť všetky výzvy

- [ ] **Journey 4: Admin dashboard**
  1. Otvoriť /admin
  2. Vidieť status posledných scraper runs
  3. Kliknúť "Trigger scrape" pre APA
  4. Vidieť status zmenu na "running" → "success"

### Validation Commands

```bash
# Backend
cd backend && npm run build     # musí prejsť bez errors
cd backend && npm run lint      # žiadne warnings
cd backend && npm test          # všetky testy PASS

# Scraper
cd scraper && python -m pytest  # unit testy
cd scraper && python main.py scrape --source apa --dry-run  # test bez DB writes

# Frontend
cd frontend && npm run build    # musí prejsť bez errors
cd frontend && npm run lint     # žiadne warnings
```

---

## Risk Assessment

| Risk | Probability | Impact | Mitigation |
|------|-------------|--------|------------|
| ITMS21 portal blokuje scraping (403/WAF) | **High** | High | Fallback na Playwright headless browser, custom headers, rate limiting (1 req/2s). Ak ani to nepomôže: manuálny import alebo alternatívny zdroj (eurofondy.gov.sk) |
| PDF extraction zlyhá (scanned PDF, corrupted) | Medium | Medium | Fallback: skip document, log warning, manual review queue. OCR cez Tesseract len ak je to blockerom |
| Supabase pgvector performance pri veľkom objeme | Low | Medium | HNSW index namiesto IVFFlat, alebo external vector DB (Pinecone) ako fallback |
| OpenAI embedding API rate limit / cost | Low | Medium | Batch processing, exponential backoff, tiktoken pre cost estimation pred embedovaním |
| APA/SIEA zmení HTML štruktúru | Medium | Medium | Abstraktné handlery, CSS selector fallbacks, monitoring + alerting na scraper failures |
| Slovenčina v search (diakritika, skloňovanie) | Medium | High | `to_tsvector('simple', ...)` pre basic matching, vector search zvládne sémantiku. V Phase 2: slovenský stemmer alebo unidecode normalizácia |

### Najväčšie riziko: ITMS21 scraping

ITMS21 portal je štátny systém s potenciálne agresívnym WAF. Research ukázal, že portal.itms21.sk občas vracia 403/infrastructure errors. Approach:

1. **Prvý pokus:** requests + custom User-Agent + session cookies
2. **Druhý pokus:** Playwright headless s random delay medzi requestmi
3. **Tretí pokus:** Reverse engineer API (ITMS21 môže mať internal JSON API pre frontend)
4. **Záložný plán:** Scrape alternatívny zdroj (eurofondy.gov.sk aggreguje ITMS výzvy) alebo manuálny seed dát pre MVP demo

---

## Acceptance Criteria

### Phase 1 MVP je "done" keď:

1. **Scraping:** Systém scrapuje výzvy z aspoň 2 z 3 zdrojov (ITMS21, APA, SIEA) automaticky
2. **Extraction:** PDF prílohy sú extrahované a chunked (aspoň 100 chunkov v DB)
3. **Search:** Hybrid search vracia relevantné výsledky pre 5 testovacích queries s precision > 70%
4. **Web App:** 
   - Zoznam výziev sa zobrazí s funkčným filtrovaním
   - Detail výzvy zobrazí metadata + atribúty
   - Search stránka vracia a zobrazuje relevantné výsledky
5. **Deploy:** Produkčná URL prístupná, všetky endpointy funkčné
6. **Performance:** Search < 2s, page load < 3s

### Testovací queries pre search validation:

| Query | Očakávaný výsledok |
|-------|-------------------|
| "kto môže žiadať o dotáciu na energetiku" | Chunky z SIEA výziev o oprávnených žiadateľoch |
| "podmienky pre neziskové organizácie" | Chunky o oprávnenosti pre NGO |
| "maximálna výška príspevku" | Chunky o alokácii a finančných podmienkach |
| "hodnotiace kritériá" | Chunky z criteria dokumentov |
| "oprávnené náklady na rekonštrukciu" | Chunky o oprávnených výdavkoch |

---

## Known Gotchas

1. **ITMS21 JavaScript rendering:** Stránka pravdepodobne vyžaduje JS pre zobrazenie výziev. Pripraviť Playwright od začiatku.
2. **ZIP v ZIP:** Niektoré zdroje majú vnorené ZIPy. Implementovať recursive unzip s max depth 2.
3. **DOCX prílohy:** Niektoré výzvy majú prílohy v DOCX formáte. Pridať python-docx extraction.
4. **Encoding issues:** Slovenské znaky (ď, ť, ň, ô, ŕ, ľ) v PDF extraction. PyMuPDF zvyčajne zvládne, ale testovať.
5. **Fulltext search vs slovenčina:** PostgreSQL `simple` config nezohľadňuje slovenský stemming. Pre MVP akceptovateľné, v Phase 2 riešiť.
6. **PDF page limit:** Max 25 strán podľa PRD. Niektoré dokumenty majú 100+ strán. Log warning, spracovať prvých 25.
7. **Supabase free tier limits:** Ak je projekt na free tier, pozor na DB size limit (500MB). Monitorovať.
8. **Rate limiting scrapers:** Nepresiahnuť 1 request/2 sekundy na zdroj, inak riziko blokovania.

## Anti-Patterns

- ❌ Nevytváraj nové patterns keď existujúce fungujú
- ❌ Nepreskakuj validáciu (každý task má svoju validáciu)
- ❌ Neignoruj failing testy
- ❌ Nehardcoduj values ktoré majú byť v config (.env)
- ❌ Nepúšťaj embedding na celý dataset naraz (batch + cost control)
- ❌ Nescrapuj bez rate limitingu (risk of IP ban)
- ❌ Nepoužívaj `any` typ v TypeScript

---

## Quality Checklist

- [x] Všetky tasky majú konkrétne súbory
- [x] Tasky sú v poradí závislostí (Week 1 backend, Week 2 frontend)
- [x] Validation strategy je executable (commands + user journeys)
- [x] Reference docs zahrnuté
- [x] Gotchas identifikované (8 items)
- [x] Risk assessment s mitigáciami
- [x] Acceptance criteria definované
- [x] **Confidence score: 7/10** (ITMS21 scraping je riziko, zvyšok straightforward)

---

**Document Version:** 1.0
**Created:** 2026-03-09
**Author:** Kodi Planner
**Status:** Ready for Review
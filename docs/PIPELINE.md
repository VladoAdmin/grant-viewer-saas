# Grant Viewer SaaS — Kompletný popis projektu

> Posledná aktualizácia: 2026-03-09 19:10 UTC
> Autor: Františka (OpenClaw)
> Účel: Tento dokument je autoritatívny zdroj kontextu pre pokračovanie vývoja. Po reštarte/compaction stačí načítať tento súbor.

---

## 1. Čo je Grant Viewer

Webová aplikácia na monitoring a inteligentné vyhľadávanie grantových výziev na Slovensku. Automaticky:
1. Scrapuje výzvy z viacerých zdrojov (ITMS21, Envirofond)
2. Sťahuje a extrahuje PDF prílohy
3. Chunkuje texty a embeduje do vektorovej DB (Supabase pgvector)
4. Poskytuje hybridné vyhľadávanie (full-text + vector similarity)
5. Extrahuje štruktúrované údaje z PDF cez vector search + GPT

**Live URL:** https://stormlevel.com/grant-viewer/

---

## 2. Architektúra

```
┌─────────────────────────────────────────────────────────────────┐
│                        STORMLEVEL.COM                           │
│  /grant-viewer/          → Static React frontend (Vite build)  │
│  /grant-viewer/api/*     → PHP proxy → Tailscale backend       │
│  /grant-viewer/proxy.php → Reverse proxy script                │
└─────────────┬───────────────────────┬───────────────────────────┘
              │                       │
              ▼                       ▼
┌──────────────────────┐   ┌──────────────────────┐
│  Supabase (priamo)   │   │  Express.js Backend  │
│  supabase-js klient  │   │  localhost:3001       │
│  grant_calls_v2      │   │  PM2: grant-viewer-api│
│  v2_call_chunks      │   │                      │
│  grant_call_*        │   │  /api/calls           │
└──────────────────────┘   │  /api/calls/:id/      │
                           │    extracted-attributes│
                           │  /api/search           │
                           │  /api/admin            │
                           └──────────┬─────────────┘
                                      │ deep=true
                                      ▼
                           ┌──────────────────────┐
                           │ Python Search API    │
                           │ Flask, localhost:3002 │
                           │ PM2: grant-viewer-   │
                           │   search-api         │
                           │                      │
                           │ POST /search-deep    │
                           │ POST /rerank         │
                           │ GET /health          │
                           └──────────────────────┘
```

### Prečo PHP proxy?
Chrome blokuje cross-origin requests na privátne IP (Tailscale 100.64.x.x) kvôli Private Network Access (PNA) politike. Ani CORS hlavičky nepomôžu. PHP proxy na stormlevel.com robí server-side forwarding, takže browser vidí same-origin request.

---

## 3. Repozitáre

### 3.1 grant-viewer-saas (Backend + Scraper)
- **GitHub:** https://github.com/VladoAdmin/grant-viewer-saas
- **Branch:** `saas-refactor` (aktívny vývoj)
- **Local:** `/home/clawd/Projects/grant-viewer-saas`
- **Posledný commit:** `db5371e` feat: add vector search attribute extraction endpoint

**Štruktúra:**
```
grant-viewer-saas/
├── scraper/                    # Python scraping + embedding pipeline
│   ├── main.py                 # CLI entry point (scrape, embed, enrich, search)
│   ├── config.py               # Konfigurácia (API URLs, model names, chunk params)
│   ├── db.py                   # Supabase DB klient (REST API wrapper)
│   ├── handlers/               # Scrapery pre jednotlivé zdroje
│   │   ├── base.py             # BaseHandler abstraktná trieda
│   │   ├── itms21.py           # ITMS21 API scraper
│   │   └── envirofond.py       # Envirofond.sk Playwright scraper
│   ├── extractor/              # PDF spracovanie
│   │   ├── pdf_extractor.py    # Text extraction z PDF (pdfplumber/PyPDF2)
│   │   ├── zip_handler.py      # ZIP/7z rozbaľovanie
│   │   ├── classifier.py       # Klasifikácia typu dokumentu (main/conditions/criteria...)
│   │   └── attribute_extractor.py  # Regex + GPT extrakcia atribútov z PDF
│   ├── embedder/               # Chunking + embedding
│   │   ├── chunker.py          # Smart chunking (768 target, 1024 max, 256 min tokens)
│   │   ├── embedder.py         # OpenAI text-embedding-3-large (3072 dim)
│   │   └── metadata_generator.py   # GPT-4o-mini metadata (summary, tags, section_title)
│   ├── search/                 # Search + reranking
│   │   ├── api.py              # Flask micro-API (port 3002)
│   │   ├── reranker.py         # GPT-4o-mini LLM reranker (scoring 0-10)
│   │   └── completeness.py     # Iteratívny RAG completeness evaluator
│   └── tests/                  # Unit + E2E testy
├── backend/                    # Express.js TypeScript API
│   └── src/
│       ├── index.ts            # Express server (port 3001)
│       ├── routes/
│       │   ├── calls.ts        # GET /api/calls, GET /api/calls/:id, GET /api/calls/:id/extracted-attributes
│       │   ├── search.ts       # GET /api/search (+ deep=true → Python API)
│       │   ├── admin.ts        # GET /api/admin/status
│       │   └── feedback.ts     # POST /api/feedback
│       ├── services/
│       │   ├── callService.ts      # Supabase queries pre výzvy
│       │   ├── searchService.ts    # Hybrid search orchestrácia
│       │   ├── extractionService.ts # Vector search + GPT extraction pre detail modal
│       │   └── pdfService.ts       # PDF export
│       └── lib/
│           ├── supabase.ts     # Supabase klient
│           └── openai.ts       # OpenAI klient
└── docs/
    ├── PRD.md                  # Product Requirements Document v1.4
    ├── PLAN.md                 # Implementation plan v2.0
    ├── PIPELINE.md             # Pipeline dokumentácia
    └── RAG_TEST_RESULTS.md     # E2E test výsledky
```

### 3.2 grant-viewer (Frontend)
- **GitHub:** https://github.com/VladoAdmin/grant-viewer
- **Branch:** `master`
- **Local:** `/home/clawd/Projects/grant-viewer`
- **Posledný commit:** `a8ad704` fix: RPC for chunked call_ids, hide API attrs, parse JSON kontakt

**Štruktúra:**
```
grant-viewer/
├── src/
│   ├── App.tsx                 # Hlavný layout: Zoznam / Časová os / Kontextové vyhľadávanie
│   ├── App.css                 # Dark theme CSS
│   ├── components/
│   │   ├── ListView.tsx        # Tabuľkový zoznam výziev (filtre, sort, semantic search)
│   │   ├── GanttView.tsx       # Časová os (vis-timeline)
│   │   ├── DetailModal.tsx     # Detail výzvy + vector search extrahované atribúty
│   │   └── DeepSearch.tsx      # Kontextové vyhľadávanie (reranker + completeness)
│   ├── lib/
│   │   ├── supabase.ts         # Supabase klient + queries (fetchCallsWithChunks via RPC)
│   │   ├── search.ts           # Client-side semantic search (OpenAI embeddings)
│   │   ├── searchApi.ts        # Deep search API volania
│   │   └── reportPdf.ts        # PDF report generátor
│   └── services/
│       └── grantSearch.ts      # Search service wrapper
├── vite.config.ts              # base: '/grant-viewer/'
├── .env                        # VITE_SUPABASE_URL, VITE_SUPABASE_KEY, VITE_OPENAI_API_KEY
└── dist/                       # Build output → deploy na stormlevel.com
```

**DÔLEŽITÉ:** Frontend volá Supabase priamo (supabase-js) pre zoznam výziev a základné údaje. Pre extrakciu atribútov a deep search volá Express backend cez PHP proxy.

---

## 4. Pipeline — Ako to funguje

### 4.1 Scraping (Zdroj → DB)

**Príkaz:** `python3 -m scraper.main scrape --source itms21|envirofond`

#### ITMS21 Flow:
1. `itms21.py` volá ITMS21 REST API (`https://api.itms21.sk/public/v1/vyzva/`)
2. Pre každú výzvu stiahne detail (`/vyzva/id/{id}`) + zoznam dokumentov
3. Uloží do `grant_calls_v2` (title, provider, status, announced_at, deadline_at, call_url)
4. Uloží dokumenty do `grant_call_attachments` (URL, file_type, filename)
5. Uloží atribúty z API do `grant_call_attributes` (Program, Kód, Alokácia, Fond, Opatrenie, Špecifický cieľ, Miesto realizácie, Oprávnení žiadatelia, Štatistiky, Kontakt)

**POZNÁMKA:** ITMS21 API atribúty sú informatívne. Presné údaje sa extrahujú z PDF cez vector search (viď 4.4).

#### Envirofond Flow:
1. `envirofond.py` používa Playwright (JS-rendered WordPress stránka)
2. Naviguje na `https://envirofond.sk/vyzvy/` a `https://envirofond.sk/aktualne-vyzva-a-specifikacie/`
3. Pre každú výzvu stiahne detail stránku, extrahuje title, deadline, status
4. Nájde PDF prílohy (linky na `.pdf`, `.docx`, `.xlsx`)
5. Uloží rovnako do `grant_calls_v2` + `grant_call_attachments`

### 4.2 Embedding (PDF → Vektory)

**Príkaz:** `python3 -m scraper.main embed --call-id <ID>`

1. **Download PDF** — stiahne prílohy pre danú výzvu
2. **Extract text** — `pdf_extractor.py` (pdfplumber) + `zip_handler.py` (7z/zip)
3. **Classify** — `classifier.py` určí typ dokumentu (main/conditions/criteria/methodology/budget/application)
4. **Chunk** — `chunker.py` rozdelí text na chunky:
   - Target: 768 tokenov
   - Max: 1024 tokenov
   - Min: 256 tokenov
   - Overlap: 100 tokenov
5. **Metadata** — `metadata_generator.py` (GPT-4o-mini) pridá:
   - `summary`: 1-2 vetný súhrn chunku
   - `content_tags`: 3-5 kľúčových slov
   - `section_title`: názov sekcie
   - `info_density`: high/medium/low/summary
6. **Enrich prefix** — každý chunk dostane prefix:
   ```
   [Výzva: {title} | Dokument: {source} | Typ: {doc_type} | Sekcia: {section_title} | Tags: {tags} | Zhrnutie: {summary}]
   ```
7. **Embed** — `text-embedding-3-large` (3072 dim) vytvorí vektor
8. **Store** — uloží do `v2_call_chunks` (content, embedding, doc_type, metadata, source)

### 4.3 Search (Query → Výsledky)

#### Základný search (frontend):
- Client-side: `supabase.rpc('match_call_chunks', {query_embedding, ...})`
- Semantic similarity na vektore

#### Hybrid search (backend):
- `hybrid_search_chunks_v2` RPC: kombinácia full-text search (`ts_rank`) + vector similarity (`1 - cosine distance`)
- Parametre: `query_text`, `query_embedding`, `match_count`, `match_threshold`, `call_id_filter`, `doc_type_filter`

#### Deep search (reranker + completeness):
- `POST /search-deep` na Python API (port 3002)
- Flow:
  1. Hybrid search → top 20 chunkov
  2. GPT-4o-mini reranker → scoring 0-10 pre každý chunk
  3. Completeness evaluator → hodnotí či odpoveď je kompletná
  4. Ak nekompletná → ďalšia iterácia s upraveným query (max 2 iterácie)

### 4.4 Extrakcia atribútov z vektorovej DB (NOVÉ)

**Endpoint:** `GET /api/calls/:id/extracted-attributes`

Flow:
1. 3 paralelné vector search queries pre daný call_id:
   - Query 1: "kód výzvy, program, špecifický cieľ, opatrenie, fond"
   - Query 2: "alokácia, finančné prostriedky, EÚ, ŠR"
   - Query 3: "oprávnení žiadatelia, miesto realizácie, posudzované obdobia, oprávnené aktivity"
2. Deduplikácia + top 15 chunkov
3. GPT-4o-mini extrahuje štruktúrované JSON (kód, program, fond, opatrenie, alokácia, miesto, žiadatelia, aktivity, obdobia, kontakt)
4. Cache v `grant_call_attributes` s prefixom `vs_` (aby sa nemuselo extrahovať znova)

**Embedding model:** `text-embedding-3-large` (3072 dim) — MUSÍ matchovať DB vektory
**Extraction model:** `gpt-4o-mini`

---

## 5. Databáza (Supabase)

**Host:** kapgabgnezcurmgcrvif.supabase.co
**Credentials:** v `/home/clawd/.openclaw/.env`

### Hlavné tabuľky:

| Tabuľka | Účel | Počet záznamov |
|---------|------|----------------|
| `grant_calls_v2` | Výzvy (ITMS21 + Envirofond) | 175 |
| `v2_call_chunks` | Embednuté PDF chunky (content + 3072-dim vector) | 1,789 |
| `grant_call_attributes` | Key-value atribúty (z API + vector search) | 3,381 |
| `grant_call_attachments` | Prílohy (URL, typ, názov) | 602 |

### Výzvy s chunkmi (6):

| call_id | Výzva | Zdroj | Chunkov |
|---------|-------|-------|---------|
| 11 | Energetická efektívnosť verejných budov (horná Nitra) | ITMS21 | 67 |
| 45 | Ochrana prírody a krajiny (manažment chránených území) | ITMS21 | 735 |
| 50 | Stoková sieť, ČOV, vodovody | ITMS21 | 531 |
| 341 | Synergická podpora (regionálna investičná pomoc) | ITMS21 | 243 |
| 358 | Vody – výzva č. B1 (2026) | Envirofond | 87 |
| 361 | Zvyšovanie energetickej účinnosti – L (2026) | Envirofond | 126 |

### Zvyšných 169 výziev nemá chunky — PDF ešte neboli spracované.

### RPC funkcie:
- `hybrid_search_chunks_v2(query_text, query_embedding, match_count, match_threshold, call_id_filter, doc_type_filter)` — hybridný search
- `match_call_chunks(query_embedding, match_count)` — čistý vector search
- `get_chunked_call_ids()` — distinct call_id z v2_call_chunks

---

## 6. Infraštruktúra

### VPS (srv1319479 / 31.97.46.222)
- **Express backend:** localhost:3001 (PM2: `grant-viewer-api`)
- **Python Search API:** localhost:3002 (PM2: `grant-viewer-search-api`)
- **Tailscale funnel:** `/grant-viewer-api` → localhost:3001

### Hosting (stormlevel.com / WebSupport)
- **Frontend:** `/grant-viewer/` — statické súbory (Vite build)
- **PHP proxy:** `/grant-viewer/proxy.php` — forward na Tailscale backend
- **SSH:** `sshpass -p '923005954b' ssh -p 25254 uid1125075@shell.r5.websupport.sk`
- **Web root:** `/data/c/4/c4830825-2b90-47cd-b33d-145e854f9393/stormlevel.com/web/grant-viewer/`

### Deploy postup:
```bash
# Build frontend
cd /home/clawd/Projects/grant-viewer && npm run build

# Vyčisti staré assets
sshpass -p '923005954b' ssh -p 25254 uid1125075@shell.r5.websupport.sk \
  'rm -rf .../stormlevel.com/web/grant-viewer/assets/'

# Upload nový build
cd dist && sshpass -p '923005954b' scp -P 25254 -r \
  * uid1125075@shell.r5.websupport.sk:.../stormlevel.com/web/grant-viewer/
```

---

## 7. Konfigurácia

### Environment (.env)
Všetky kľúče v `/home/clawd/.openclaw/.env`:
- `OPENAI_API_KEY` — pre embedding (text-embedding-3-large) a GPT-4o-mini
- `SUPABASE_URL`, `SUPABASE_KEY`, `SUPABASE_SERVICE_KEY` — Supabase REST API
- `SUPABASE_HOST`, `SUPABASE_USER`, `SUPABASE_PASSWORD` — PostgreSQL priamy prístup

### Embedding model
- **Model:** `text-embedding-3-large`
- **Dimenzia:** 3072
- **KRITICKÉ:** Všetky vektory v DB sú 3072-dim. Nemeniť model bez migrácie.

### Chunk parametre
- Target: 768 tokenov
- Max: 1024 tokenov
- Min: 256 tokenov
- Overlap: 100 tokenov

### Metadata model
- `gpt-4o-mini` — pre summary, tags, section_title, reranking, completeness, extrakciu atribútov

---

## 8. Frontend — Ako funguje

### Záložky:
1. **📋 Zoznam** — tabuľka výziev s filtrami (zdroj, stav, text search)
2. **📊 Časová os** — Gantt timeline (vis-timeline)
3. **🔍 Kontextové vyhľadávanie** — deep search s rerankerom + completeness

### Dáta:
- Frontend zobrazuje **len výzvy s chunkmi** (6 výziev)
- Zoznam: `supabase.rpc('get_chunked_call_ids')` → `grant_calls_v2.in('id', callIds)`
- "Zobraziť aj uzavreté" checkbox rozšíri filter (aktuálne všetkých 6 je aktívnych)

### Detail modal:
1. Otvorí sa po kliknutí na výzvu
2. Základné údaje: z `grant_calls_v2` (title, provider, status, announced_at, deadline_at)
3. **Extrahované atribúty z PDF:** volá Express backend `GET /api/calls/:id/extracted-attributes`
   - Loading spinner: "Načítavam údaje z dokumentov..."
   - Sekcie: Základné info, Špecifický cieľ, Financovanie, Miesto, Žiadatelia, Aktivity, Obdobia, Kontakt
   - Cachované — druhé otvorenie je okamžité
4. Prílohy: z `grant_call_attachments`
5. PDF export: generuje sumár výzvy

### Dark theme:
- Pozadie: `#0f172a`
- Surface: `#1e293b`
- StormLevel logo v headeri

---

## 9. Náklady

| Operácia | Odhadovaná cena |
|----------|-----------------|
| Embedding 1 výzvy (full pipeline) | ~$0.08 |
| Enrichment 243 chunkov (metadata) | ~$0.50 |
| Deep search query | ~$0.02 |
| Extrakcia atribútov (3 queries + GPT) | ~$0.01 |
| Embedding všetkých 175 výziev | ~$15-20 (odhad) |

---

## 10. CLI príkazy

```bash
cd /home/clawd/Projects/grant-viewer-saas
source /home/clawd/.openclaw/.env

# Scrape výzvy
python3 -m scraper.main scrape --source itms21
python3 -m scraper.main scrape --source envirofond

# Embed PDF pre konkrétnu výzvu
python3 -m scraper.main embed --call-id 11

# Enrich chunky (metadata + re-embed)
python3 -m scraper.main enrich --call-id 341

# Search (CLI)
python3 -m scraper.main search "vodovody obce"

# PM2
pm2 list
pm2 restart grant-viewer-api
pm2 restart grant-viewer-search-api
pm2 logs grant-viewer-api --lines 20
```

---

## 11. Čo treba dorobiť (Next Steps)

1. **Spustiť embedding pipeline pre zvyšných 169 výziev** — aktuálne len 6 z 175 má chunky
2. **Pridať ďalšie zdroje** — ISPP, SIEA, nadácie, APVV (viď PRD.md)
3. **Benchmark chunk parametrov** — optimalizovať target/max/min/overlap
4. **Auth + multi-tenancy** — prihlásenie, organizácie (PRD Phase 2)
5. **Notifikácie** — email/push pri nových výzvach (PRD Phase 2)
6. **AI chatbot** — konverzačné rozhranie nad vektorovou DB (PRD Phase 3)

---

## 12. Známe problémy a lessons learned

1. **Supabase default limit = 1000 riadkov** — `supabase.from('table').select()` vracia max 1000. Riešenie: RPC funkcia `get_chunked_call_ids()`.
2. **Chrome PNA blokuje Tailscale** — cross-origin na privátne IP nefunguje. Riešenie: PHP proxy na stormlevel.com.
3. **DVA frontend repá** — `grant-viewer` (pôvodný, LIVE) vs `grant-viewer-saas/frontend/` (nový, nepoužívaný). Vždy pracuj v `grant-viewer`.
4. **Embedding model nesmie byť zmenený** — `text-embedding-3-large` (3072 dim). Ak sa zmení, treba re-embedovať všetky chunky.
5. **Envirofond vyžaduje Playwright** — WordPress stránka je JS-rendered, requests/BeautifulSoup nefungujú.
6. **ITMS21 API údaje vs PDF údaje** — API alokácia (26M) sa líši od PDF alokácie (15.8M) pre call_id 11. PDF je pôvodná suma, API je aktualizovaná. Vlado preferuje PDF údaje.
7. **vs_ prefix** — atribúty extrahované z vektorovej DB majú prefix `vs_` v `grant_call_attributes`. Frontend ich zobrazuje, API atribúty (bez prefixu) skrýva.

---

## 13. Trello karty

Board: "New SaaS" (ID: `69a96646d0161b280d84f2af`)

Aktualizované karty:
- [FEATURE] Envirofond handler — DONE
- [DOC] Pipeline Documentation — DONE  
- [FEATURE] Vector search attribute extraction — DONE
- [FEATURE] Frontend: len výzvy s chunkami — DONE
- [FEATURE] Deep search (reranker + completeness) — DONE
- [PENDING] Embedding pipeline pre všetky výzvy — TODO

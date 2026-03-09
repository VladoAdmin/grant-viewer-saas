# E2E Test Context — Grant Viewer SaaS

> Tento súbor obsahuje kompletný kontext pre end-to-end testovanie pipeline.
> Vytvorené: 2026-03-09 12:53 UTC

## Čo treba testovať

Vlado chce otestovať celý pipeline so živými dátami:
1. Nájsť výzvu na ITMS21
2. Stiahnuť/scrapovať údaje
3. Extrahovať PDF prílohy
4. Embedovať do vektorovej DB
5. Vyhľadať údaje cez hybrid search z vektorovej DB
6. Porovnať: extrahované údaje z DB == údaje v pôvodných PDF dokumentoch

## Aktuálny stav DB

- **grant_calls_v2:** 123 záznamov (existujúce z grant-scraper)
- **v2_call_chunks:** 2,528 chunkov (existujúce embeddingy)
- **grant_call_attributes:** 35 záznamov (nové z Kodi Coder Week 1)
- **grant_call_attachments:** existuje, prepojené na grant_calls_v2

## DB Schéma (hlavné tabuľky)

### grant_calls_v2
- id (bigint PK), source, source_url, call_url, title, announced_at, deadline_at
- provider, call_type, total_allocation, status, closed_at, created_at, updated_at, deleted_at

### v2_call_chunks
- Chunk tabuľka s embeddings (vector stĺpec)

### grant_call_attributes
- id, grant_call_id (FK → grant_calls_v2), key, value, value_type, extracted_at

### grant_call_attachments
- grant_call_id (FK → grant_calls_v2), filename, url, atď.

## Scraper CLI

```bash
cd /home/clawd/Projects/grant-viewer-saas
python -m scraper.main scrape --source itms21 --limit 1
python -m scraper.main embed --call-id <ID>
python -m scraper.main cleanup --months 12
python -m scraper.main dedup
python -m scraper.main export-pdf --call-id <ID> --output call.pdf
python -m scraper.main status
```

## Scraper Config (scraper/config.py)

- EMBED_MODEL: text-embedding-3-small
- EMBED_DIM: 1536
- CHUNK_TARGET_TOKENS: 768
- CHUNK_MAX_TOKENS: 1024
- CHUNK_MIN_TOKENS: 256
- ITMS21_API_BASE: https://api.itms21.sk/public/v1
- DB: Supabase REST API (SUPABASE_URL + SUPABASE_SERVICE_ROLE_KEY)

## Backend API

```bash
# Lokálne
cd /home/clawd/Projects/grant-viewer-saas/backend
npm run dev  # port 3001

# Produkcia (PM2 na VPS)
# API: https://srv1319479.tailcd1c2c.ts.net/grant-viewer-api/api/
```

### Endpoints:
- GET /api/calls — zoznam výziev
- GET /api/calls/:id — detail výzvy
- POST /api/search — hybrid search (body: { query, limit })
- GET /api/calls/:id/export-pdf — PDF export
- GET /api/admin/status — admin dashboard
- POST /api/admin/trigger — spustiť scraping
- POST /api/feedback — odoslať spätnú väzbu

## Frontend

```bash
cd /home/clawd/Projects/grant-viewer-saas/frontend
npm run dev  # port 5173
```

- Produkcia: https://stormlevel.com/grant-viewer/

## Hybrid Search RPC

V Supabase existuje funkcia `hybrid_search_chunks` (RPC).
Parametre: query_text, query_embedding, match_count, rrf_k

## Kľúčové Python súbory

| Súbor | Čo robí |
|-------|---------|
| scraper/main.py | CLI vstupný bod |
| scraper/config.py | Konfigurácia |
| scraper/db.py | Supabase REST klient |
| scraper/handlers/itms21.py | ITMS21 API scraper |
| scraper/handlers/base.py | Základné typy (GrantCall, Attachment) |
| scraper/extractor/pdf_extractor.py | PDF text extraction |
| scraper/extractor/classifier.py | Dokument klasifikácia |
| scraper/extractor/zip_handler.py | ZIP rozbalenie |
| scraper/embedder/chunker.py | Smart chunking |
| scraper/embedder/embedder.py | OpenAI embedding |
| scraper/pdf_export.py | PDF export pre výzvu |
| scraper/error_handler.py | Error handling s error_id |
| scraper/cleanup.py | Cleanup + dedup |

## Existujúce výzvy v DB (príklady)

| ID | Title |
|----|-------|
| 9 | Výzva na podporu energetickej efektívnosti a využívania OZE v podnikoch |
| 6 | Vytvorenie systému podpory domácností ohrozených energetickou chudobou |
| 11 | Výzva na podporu energetickej efektívnosti verejných budov regiónu hornej Nitry |

## Čo NEFUNGUJE (známe issues)

1. Kodi Coder kód referencuje `grant_calls` tabuľku ale v DB je `grant_calls_v2`
2. Embedding dimenzia: config hovorí 1536, ale existujúce chunky sú 3072-dim
3. Migrácia 001_initial_schema.sql nebola spustená (ADD tabuľky existujú, ale hlavná grant_calls nie)
4. ITMS21 API vracia sparse data pre deadline, status

## Test Postup

1. **Vyber výzvu:** Vyber jednu konkrétnu výzvu z DB (napr. ID 6 alebo 9)
2. **Over PDF prílohy:** Stiahni PDF a ručne prečítaj kľúčové údaje
3. **Spusti embed (ak treba):** `python -m scraper.main embed --call-id <ID>`
4. **Hybrid search:** Opýtaj sa vektorovej DB na konkrétne údaje z tej výzvy
5. **Porovnaj:** Sú extrahované údaje kompletné a správne?
6. **Ak chýbajú:** Identifikuj čo chýba a prečo (chunking? embedding? search?)

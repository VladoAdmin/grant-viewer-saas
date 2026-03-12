# GRV01 — Grant Viewer SaaS

## Aktuálny stav
- **Fáza:** Week 2/4 (MVP Phase 1)
- **Posledná aktivita:** 2026-03-09 19:10 UTC
- **Posledný commit:** `db5371e` (vector search attribute extraction)

## Čo je hotové ✅
- Week 1+2 (scraping, backend, frontend)
- RAG + Envirofond handler
- Deep search (reranker + completeness)
- 176 výziev v DB (ITMS21 + Envirofond)

## Čo ide teraz 🔄
- Embedding pipeline pre zvyšných 169 výziev (6/175 hotových)

## Blockers ⏳
- Čakám na Vladove inštrukcie (povedal "zajtra" 2026-03-09)

## Rozhodnutia
- Používame `text-embedding-3-large` (3072 dim)
- Frontend je v `grant-viewer/` repo (nie `grant-viewer-saas/frontend/`)
- PDF údaje majú prioritu pred API údajmi

## Linky
- **GitHub:** https://github.com/VladoAdmin/grant-viewer-saas
- **Branch:** `saas-refactor`
- **Trello:** karty s prefixom `GRV01-`
- **Live:** https://stormlevel.com/grant-viewer/
- **PIPELINE.md:** pozri sekcia 11 "Čo treba dorobiť"

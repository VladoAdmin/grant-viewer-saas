# Grant Viewer SaaS — Product Requirements Document

## 1. Executive Summary

**Grant Viewer** je SaaS platforma pre monitoring a inteligentné vyhľadávanie grantových výziev na Slovensku. Systém automaticky scrapuje výzvy z viacerých zdrojov, extrahuje štruktúrované dáta z PDF príloh, embeduje ich do vektorovej databázy a poskytuje kontextové vyhľadávanie cez AI.

## 2. Problem Statement

**Súčasný stav:**
- Grantové výzvy sú rozptýlené na 10+ portáloch (ITMS21, ISPP, SIEA, nadácie...)
- Detailné podmienky sú v PDF prílohách, často zozipovaných
- Podnikatelia a neziskovky strácia hodiny hľadaním relevantných výziev
- Existujúce riešenia nemajú sémantické vyhľadávanie v obsahu PDF

**Cieľová skupina:**
- Malé a stredné podniky hľadajúce dotácie
- Neziskové organizácie
- Samosprávy (obce, mestá)
- Grantoví konzultanti

## 3. Solution Overview

### 3.1 System Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        GRANT VIEWER SAAS                         │
├─────────────────────────────────────────────────────────────────┤
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────┐ │
│  │   Web App    │  │   Admin      │  │   API Gateway        │ │
│  │   (React)    │  │   Dashboard  │  │   (Express)          │ │
│  └──────────────┘  └──────────────┘  └──────────────────────┘ │
├─────────────────────────────────────────────────────────────────┤
│                         CORE SERVICES                            │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────┐   │
│  │ GrantScraper │  │ DocExtractor │  │  VectorSearch      │   │
│  │ (Scheduler)  │  │ (Classifier)   │  │  (Hybrid)          │   │
│  └──────────────┘  └──────────────┘  └──────────────────────┘   │
├─────────────────────────────────────────────────────────────────┤
│                         DATA LAYER                               │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────┐   │
│  │  PostgreSQL  │  │  pgvector    │  │  Object Storage      │   │
│  │  (Supabase)  │  │  (embeddings)│  │  (PDF cache)         │   │
│  └──────────────┘  └──────────────┘  └──────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
```

### 3.2 Data Flow

```
1. SCHEDULER (cron) → spustí GrantScraper každých 6 hodín
2. SCRAPER → nájde nové výzvy → uloží do grant_calls_v2
3. EXTRACTOR → stiahne ZIP/PDF → klasifikuje dokumenty
4. CHUNKER → rozdelí text na 400-tokenové chunky s 50-token overlap
5. EMBEDDER → OpenAI text-embedding-3-large (3072 dim) → v2_call_chunks
6. SEARCH → Hybrid (vector + BM25) → kontextové odpovede
```

## 4. Functional Requirements

### 4.1 GrantScraper Module

| ID | Requirement | Priority |
|----|-------------|----------|
| GS-001 | Scrapuje ITMS21, ISPP, SIEA, Planobnovy, nadácie | P0 |
| GS-002 | Detekuje nové výzvy (porovnanie s DB) | P0 |
| GS-003 | Sťahuje základné údaje: názov, alokácia, deadline, zdroj | P0 |
| GS-004 | Sťahuje prílohy (ZIP/PDF) do object storage | P0 |
| GS-005 | Ukladá metadata o prílohách do grant_call_attachments | P0 |
| GS-006 | Scheduler: každých 24 hodín (cron) | P1 |
| GS-007 | Notifikácia o nových výzvach (email/Telegram) | P2 |

### 4.2 DocExtractor Module

| ID | Requirement | Priority |
|----|-------------|----------|
| DE-001 | Rozbaľuje ZIP archívy | P0 |
| DE-002 | Extrahuje text z PDF (PyMuPDF) | P0 |
| DE-003 | **Klasifikuje dokumenty:** | P0 |
| DE-003a | `main` — hlavná výzva, špecifikácia | P0 |
| DE-003b | `conditions` — podmienky, oprávnení žiadatelia | P0 |
| DE-003c | `criteria` — hodnotiace kritériá | P0 |
| DE-004 | `costs` — oprávnené náklady/výdavky | P1 |
| DE-005 | `skip` — formuláre, GDPR, vzory (nepodstatné) | P0 |
| DE-006 | Používa AI (GPT-4o-mini) na klasifikáciu keď nie je istý | P1 |
| DE-007 | Ukladá klasifikáciu do doc_classification tabuľky | P1 |

### 4.3 Chunker & Embedder Module

| ID | Requirement | Priority |
|----|-------------|----------|
| CE-001 | Chunk size: 400 tokens target, 256-512 range | P0 |
| CE-002 | Overlap: 50 tokens medzi chunkmi | P0 |
| CE-003 | Split na odstavce (`\n\n`), potom vety | P0 |
| CE-004 | **Kontextový prefix:** | P0 |
| CE-004a | Názov výzvy | P0 |
| CE-004b | Názov dokumentu | P0 |
| CE-004c | Názov sekcie (ak detekovaný) | P1 |
| CE-005 | Embedding model: OpenAI text-embedding-3-large (3072 dim) | P0 |
| CE-006 | Ukladá do v2_call_chunks: call_id, content, embedding, chunk_index, source | P0 |

### 4.4 VectorSearch Module

| ID | Requirement | Priority |
|----|-------------|----------|
| VS-001 | **Hybrid search:** kombinácia vector + fulltext | P0 |
| VS-002 | BM25 pre keyword matching | P0 |
| VS-003 | Cosine similarity pre sémantické hľadanie | P0 |
| VS-004 | RRF (Reciprocal Rank Fusion) pre kombináciu | P0 |
| VS-005 | Filter na call_id (search v rámci jednej výzvy) | P0 |
| VS-006 | Filter na doc_type (main/conditions/criteria) | P1 |
| VS-007 | Threshold: 0.3 pre vector, 0.1 pre hybrid | P0 |
| VS-008 | Limit: 5-10 výsledkov | P0 |

### 4.5 GrantViewer Web App

| ID | Requirement | Priority |
|----|-------------|----------|
| GV-001 | Zobrazenie zoznamu otvorených výziev | P0 |
| GV-002 | Filtrovanie: zdroj, status, deadline, alokácia | P0 |
| GV-003 | **Kontextové vyhľadávanie** — prirodzený jazyk | P0 |
| GV-004 | Zobrazenie detailu výzvy s extrahovanými atribútmi | P0 |
| GV-005 | Zobrazenie zdrojových dokumentov (PDF viewer) | P1 |
| GV-006 | Notifikácie o nových výzvach (email) | P2 |
| GV-007 | Export výzvy do PDF reportu | P2 |
| GV-008 | Admin dashboard pre správu zdrojov | P2 |

## 5. Non-Functional Requirements

### 5.1 Performance

| Metric | Target |
|--------|--------|
| Scraper latency | < 5 min pre všetky zdroje |
| Extraction latency | < 2 min na výzvu |
| Embedding throughput | > 100 chunks/min |
| Search latency | < 500ms |
| Web app TTFB | < 1s |

### 5.2 Scalability

- Podpora 1000+ aktívnych výziev
- 100K+ chunks v vector DB
- 100+ súbežných používateľov

### 5.3 Reliability

- 99.9% uptime pre scraper (s retries)
- Idempotentné operácie (re-embed bez duplikátov)
- Circuit breaker pre externé API

### 5.4 Security

- API keys v .env, nie v kóde
- Supabase RLS policies
- PDF download rate limiting
- No PII storage

## 6. Technical Stack

| Layer | Technology |
|-------|------------|
| Frontend | React 18 + TypeScript + Tailwind CSS |
| Backend API | Express.js + TypeScript |
| Database | Supabase (PostgreSQL + pgvector) |
| Vector Search | Hybrid (pgvector + fulltext) |
| Scraping | Python + requests + BeautifulSoup |
| PDF Extraction | PyMuPDF (fitz) |
| DOCX Extraction | python-docx |
| AI/LLM | OpenAI GPT-4o-mini (extraction) |
| Embeddings | OpenAI text-embedding-3-large |
| Scheduler | n8n / cron |
| Hosting | Vercel (frontend) + VPS (backend) |
| Monitoring | OpenClaw heartbeat |

## 7. Data Model

### 7.1 Core Tables

```sql
-- Grant calls (scraped)
CREATE TABLE grant_calls_v2 (
    id SERIAL PRIMARY KEY,
    source TEXT NOT NULL, -- 'portal.itms21.sk', 'ispp.apa.sk', etc.
    source_url TEXT,
    call_url TEXT NOT NULL,
    title TEXT NOT NULL,
    call_details TEXT,
    announced_at DATE,
    deadline_at DATE,
    provider TEXT,
    call_type TEXT,
    total_allocation TEXT,
    status TEXT DEFAULT 'Otvorená',
    closed_at DATE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Attachments (downloaded files)
CREATE TABLE grant_call_attachments (
    id SERIAL PRIMARY KEY,
    grant_call_id INTEGER REFERENCES grant_calls_v2(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    url TEXT NOT NULL,
    file_type TEXT, -- 'pdf', 'zip', 'docx'
    downloaded_at TIMESTAMPTZ,
    local_path TEXT -- path in object storage
);

-- Document classification (AI-classified)
CREATE TABLE doc_classification (
    id SERIAL PRIMARY KEY,
    grant_call_id INTEGER REFERENCES grant_calls_v2(id) ON DELETE CASCADE,
    attachment_id INTEGER REFERENCES grant_call_attachments(id),
    doc_type TEXT NOT NULL, -- 'main', 'conditions', 'criteria', 'costs', 'skip'
    confidence FLOAT,
    classified_at TIMESTAMPTZ DEFAULT NOW()
);

-- Vector chunks (for semantic search)
CREATE TABLE v2_call_chunks (
    id SERIAL PRIMARY KEY,
    call_id INTEGER REFERENCES grant_calls_v2(id) ON DELETE CASCADE,
    content TEXT NOT NULL,
    embedding vector(3072), -- OpenAI text-embedding-3-large
    chunk_index INTEGER,
    source TEXT, -- document name
    doc_type TEXT, -- 'main', 'conditions', etc.
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Extracted attributes (structured data)
CREATE TABLE grant_call_attributes (
    id SERIAL PRIMARY KEY,
    grant_call_id INTEGER REFERENCES grant_calls_v2(id) ON DELETE CASCADE,
    key TEXT NOT NULL,
    value TEXT NOT NULL,
    extracted_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(grant_call_id, key)
);

-- Fulltext search (for hybrid search)
CREATE INDEX idx_v2_call_chunks_fts ON v2_call_chunks 
USING gin(to_tsvector('simple', content));

-- Vector index
CREATE INDEX idx_v2_call_chunks_embedding ON v2_call_chunks 
USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);
```

### 7.2 RPC Functions

```sql
-- Hybrid search with RRF fusion
CREATE OR REPLACE FUNCTION hybrid_search_chunks(
    query_text TEXT,
    query_embedding vector(3072),
    match_threshold FLOAT,
    match_count INT,
    call_id_filter INT DEFAULT NULL
)
RETURNS TABLE (
    id INT,
    call_id INT,
    content TEXT,
    source TEXT,
    doc_type TEXT,
    similarity FLOAT,
    rank INT
) AS $$
BEGIN
    RETURN QUERY
    WITH vector_results AS (
        SELECT 
            c.id,
            c.call_id,
            c.content,
            c.source,
            c.doc_type,
            1 - (c.embedding <=> query_embedding) AS similarity,
            ROW_NUMBER() OVER (ORDER BY c.embedding <=> query_embedding) AS vector_rank
        FROM v2_call_chunks c
        WHERE (call_id_filter IS NULL OR c.call_id = call_id_filter)
        AND 1 - (c.embedding <=> query_embedding) > match_threshold
        ORDER BY c.embedding <=> query_embedding
        LIMIT match_count * 2
    ),
    text_results AS (
        SELECT 
            c.id,
            c.call_id,
            c.content,
            c.source,
            c.doc_type,
            ts_rank(to_tsvector('simple', c.content), plainto_tsquery('simple', query_text)) AS similarity,
            ROW_NUMBER() OVER (ORDER BY ts_rank(to_tsvector('simple', c.content), plainto_tsquery('simple', query_text)) DESC) AS text_rank
        FROM v2_call_chunks c
        WHERE (call_id_filter IS NULL OR c.call_id = call_id_filter)
        AND to_tsvector('simple', c.content) @@ plainto_tsquery('simple', query_text)
        ORDER BY similarity DESC
        LIMIT match_count * 2
    ),
    combined AS (
        SELECT 
            COALESCE(v.id, t.id) AS id,
            COALESCE(v.call_id, t.call_id) AS call_id,
            COALESCE(v.content, t.content) AS content,
            COALESCE(v.source, t.source) AS source,
            COALESCE(v.doc_type, t.doc_type) AS doc_type,
            COALESCE(v.similarity, 0) + COALESCE(t.similarity, 0) * 0.5 AS combined_score,
            COALESCE(1.0 / (60 + v.vector_rank), 0) + COALESCE(1.0 / (60 + t.text_rank), 0) AS rrf_score
        FROM vector_results v
        FULL OUTER JOIN text_results t ON v.id = t.id
    )
    SELECT 
        c.id,
        c.call_id,
        c.content,
        c.source,
        c.doc_type,
        c.combined_score AS similarity,
        ROW_NUMBER() OVER (ORDER BY c.rrf_score DESC) AS rank
    FROM combined c
    ORDER BY c.rrf_score DESC
    LIMIT match_count;
END;
$$ LANGUAGE plpgsql;
```

## 8. User Stories

### 8.1 End Users

| ID | Story | Priority |
|----|-------|----------|
| US-001 | Ako podnikateľ chcem vidieť všetky otvorené výzvy, aby som nezmeškal príležitosť | P0 |
| US-002 | Ako neziskovka chcem vyhľadať "výzvy pre sociálne projekty", aby som našiel relevantné granty | P0 |
| US-003 | Ako používateľ chcem vedieť "kto môže žiadať" a "na čo sa dá použiť", aby som posúdil oprávnenosť | P0 |
| US-004 | Ako používateľ chcem filtrovať podľa deadline, alokácie, zdroja, aby som si zúžil výber | P1 |
| US-005 | Ako používateľ chcem exportovať výzvu do PDF reportu, aby som ju mohol zdieľať | P2 |
| US-006 | Ako používateľ chcem notifikácie o nových výzvach v mojej oblasti, aby som nič nezmeškal | P2 |

### 8.2 Admin Users

| ID | Story | Priority |
|----|-------|----------|
| AD-001 | Ako admin chcem vidieť stav scraperov a posledný successful run | P1 |
| AD-002 | Ako admin chcem manuálne spustiť re-scrape konkrétneho zdroja | P1 |
| AD-003 | Ako admin chcem vidieť štatistiky: počet výziev, chunkov, search queries | P2 |
| AD-004 | Ako admin chcem upraviť classification pravidlá pre nové zdroje | P2 |

## 9. Success Metrics

| Metric | Target | Measurement |
|--------|--------|-------------|
| **Coverage** | 95% otvorených výziev na SK | Počet výziev v DB vs. manuálny audit |
| **Freshness** | < 6 hodín od vyhlásenia | Čas medzi vyhlásením a objavením v systéme |
| **Search Precision** | > 80% top-3 relevantné | Manuálne hodnotenie 50 search queries |
| **Search Recall** | > 90% pre definované otázky | Test set 20 otázok s known answers |
| **User Engagement** | > 30% vracajúcich sa používateľov | Analytics (pripravené na Phase 2) |
| **System Uptime** | > 99% | Monitoring heartbeat |

## 10. Technical Constraints

### 10.1 Hard Constraints

- **Jazyk:** Slovenčina (s diakritikou)
- **Zdroje:** Verejné API a web scraping (legálne, bez bypassov)
- **PDF Processing:** Max 25 strán na dokument (performance)
- **Embedding dim:** 3072 (OpenAI large) — vyžaduje HNSW index
- **Hosting:** Vercel (frontend) + VPS (backend) + Supabase (DB)

### 10.2 Soft Constraints

- Latency: < 500ms pre search (cieľ), < 2s akceptovateľné
- Cost: < $10/mesiac pre embedding API
- Storage: < 10GB pre PDF cache

## 11. Phase 1 MVP Scope (Week 1-2)

### Must Have (P0)

1. **GrantScraper** — ITMS21 + ISPP + SIEA (3 hlavné zdroje)
2. **DocExtractor** — ZIP unpacking, PDF text extraction, basic classification
3. **Chunker** — 400 tokens, 50 overlap, context prefix
4. **Embedder** — OpenAI text-embedding-3-large
5. **Hybrid Search** — vector + fulltext ILIKE
6. **Web App** — list výziev, detail, search box
7. **Admin** — status dashboard, manual trigger

### Should Have (P1) — Week 3-4

- Všetky zdroje (Planobnovy, nadácie, culture.gov)
- AI classification (GPT-4o-mini)
- Advanced filters (deadline, alokácia)
- User accounts (Supabase Auth)
- Email notifikácie

### Nice to Have (P2) — Phase 2

- PDF report export
- API pre third-party integrácie
- Mobile app
- Multi-language (CZ, HU)
- AI chatbot (RAG)

## 12. Risks & Mitigations

| Risk | Probability | Impact | Mitigation |
|------|-------------|--------|------------|
| Zmena štruktúry zdrojov | High | High | Abstraktné handlery, monitoring, alerty |
| PDF extraction failures | Medium | Medium | Fallback na OCR, manual review queue |
| Embedding API rate limits | Low | Medium | Exponential backoff, caching |
| Cost overrun | Low | High | Budget alerts, usage monitoring |
| Search quality low | Medium | High | Hybrid search, reranking, feedback loop |

## 13. Appendix

### A. Source URLs

| Source | URL Pattern | Handler |
|--------|-------------|---------|
| ITMS21 | https://www.itms21.sk/... | ITMS21Handler |
| ISPP | https://www.apa.sk/... | ISPPApaHandler |
| SIEA | https://www.siea.sk/... | SIEAHandler |
| Planobnovy | https://www.planobnovy.sk/... | PlanobnoyHandler |
| Envirofond | https://www.envirofond.sk/... | EnvirofondHandler |
| Culture | https://www.culture.gov.sk/... | CultureGovHandler |

### B. Document Classification Rules

```python
CLASSIFICATION_RULES = {
    'main': {
        'keywords': ['výzva', 'vyzva', 'špecifikácia', 'specifikacia', 
                     'všeobecné podmienky', 'usmernenie'],
        'min_pages': 5,
        'priority': 1
    },
    'conditions': {
        'keywords': ['podmienky', 'oprávnený žiadateľ', 'oprávnenosť',
                     'príručka', 'prirucka', 'synergické účinky'],
        'min_pages': 2,
        'priority': 2
    },
    'criteria': {
        'keywords': ['kritériá', 'hodnotenie', 'vyhodnotenie',
                     'príloha č. 2', 'priloha 2'],
        'min_pages': 2,
        'priority': 3
    },
    'costs': {
        'keywords': ['náklady', 'výdavky', 'rozpočet', 'financovanie',
                     'číselník', 'cenník'],
        'min_pages': 1,
        'priority': 4
    },
    'skip': {
        'keywords': ['formulár', 'vzor', 'gdpr', 'čestné vyhlásenie',
                     'kontakty', 'komisia', 'manual', 'pouzivatelsky'],
        'priority': 0
    }
}
```

### C. API Endpoints

```
GET  /api/calls              # List all calls (with filters)
GET  /api/calls/:id          # Detail of specific call
GET  /api/calls/:id/attributes  # Extracted structured data
POST /api/search             # Hybrid search
     Body: { query: string, call_id?: number, limit?: number }
GET  /api/admin/status       # Scraper status
POST /api/admin/trigger      # Manual scraper trigger
```

---

**Document Version:** 1.0  
**Last Updated:** 2026-03-09  
**Author:** Františka (Kodi Team)  
**Status:** Ready for Review

# GrantBot V2

Dvojfázový scraping systém pre grantové výzvy.

## Architektúra

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│   DISCOVERY     │────▶│   ENRICHMENT    │────▶│   MANUAL AUDIT  │
│   (Fáza 1)      │     │   (Fáza 2)      │     │   (fallback)    │
└─────────────────┘     └─────────────────┘     └─────────────────┘
```

### Fáza 1: Discovery
- Rýchle nájdenie všetkých odkazov na zdrojových stránkach
- LLM klasifikácia: je to grantová výzva? (open/planned/closed)
- Ukladanie do `v2_discovered_calls`
- **Cieľ:** Coverage — nájsť všetko

### Fáza 2: Enrichment
- Hĺbkové spracovanie každej kvalifikovanej výzvy
- LLM extrakcia detailov (deadline, provider, podmienky, ...)
- Playwright pre JS-heavy stránky
- Ukladanie do `v2_enriched_calls`
- **Cieľ:** Kvalita dát

### Manual Audit
- Výzvy, ktoré zlyhali 3× idú do `manual_audit_queue`
- View pre manuálne review

## Inštalácia

```bash
cd /home/clawd/Projects/grant-scraper/v2

# Nainštaluj závislosti
pip install -r requirements_v2.txt

# Playwright browsers
playwright install chromium
```

## Database setup

```bash
# Apply migrations
psql $SUPABASE_URL -f ../sql/migrations_v2/001_discovery.sql
psql $SUPABASE_URL -f ../sql/migrations_v2/002_enrichment.sql
```

## Použitie

### Inicializácia zdrojov
```bash
python -m v2.discovery --init-sources
```

### Spustenie discovery (len fáza 1)
```bash
python -m v2.discovery
```

### Spustenie enrichment (len fáza 2)
```bash
python -m v2.enrichment
```

### Celý pipeline
```bash
python -m v2.run_v2
```

### Špecifické zdroje
```bash
python -m v2.run_v2 --sources planobnovy mirri
```

### Len discovery (preskočiť enrichment)
```bash
python -m v2.run_v2 --skip-enrichment
```

### Len enrichment (na už objavených)
```bash
python -m v2.run_v2 --skip-discovery
```

## Konfigurácia

Nastav v `.env`:
```
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_KEY=your-service-role-key

# LLM (jeden z týchto)
OPENROUTER_API_KEY=your-key
# alebo
OPENAI_API_KEY=your-key
# alebo
ANTHROPIC_API_KEY=your-key

# Optional: default model
LLM_MODEL=openai/gpt-4o-mini
```

## Monitoring

### Zobrazenie queue
```sql
-- Kvalifikované výzvy čakajúce na enrichment
SELECT * FROM v2_calls_ready_for_enrichment;

-- Manual audit queue
SELECT * FROM v2_manual_audit_queue;

-- Štatistiky
SELECT 
    discovery_status,
    call_status,
    COUNT(*) 
FROM v2_discovered_calls 
GROUP BY discovery_status, call_status;
```

## Štruktúra projektu

```
v2/
├── __init__.py           # Package exports
├── models.py             # Pydantic modely
├── llm_client.py         # LLM wrapper
├── storage_v2.py         # DB operácie
├── discovery.py          # Fáza 1: Discovery
├── enrichment.py         # Fáza 2: Enrichment
├── run_v2.py             # Main orchestrator
└── config_v2.yaml        # (optional) Source config

sql/migrations_v2/
├── 001_discovery.sql     # Discovery tabuľky
└── 002_enrichment.sql    # Enrichment tabuľky
```

## Rozdiely od V1

| V1 (stare) | V2 (nové) |
|------------|-----------|
| Jednofázový | Dvojfázový (discovery → enrichment) |
| Template-based | LLM-based |
| Fragilné selektory | Odolné voči zmenám layoutu |
| Spoločná tabuľka | Oddelené `v2_*` tabuľky |
| Ťažko debugovateľné | Audit trail pre každý krok |
| Fallback: nič | Fallback: manual audit |

## TODO

- [ ] Crawl4AI integrácia pre lepšie JS stránky
- [ ] Retry mechanizmus s exponential backoff
- [ ] Webhook notifikácie pri nových výzvach
- [ ] Dashboard pre monitoring

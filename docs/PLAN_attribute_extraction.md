# Plan: Attribute Extraction from PDF Attachments

## Kontext

E2E testovanie odhalilo, že ITMS21 API je len informatívny zdroj (otvorená/zatvorená). Kľúčové údaje (announced_at, total_allocation, kód výzvy, oprávnení žiadatelia, atď.) treba extrahovať z PDF príloh, nie z API.

## Aktuálny stav

- `scraper/handlers/itms21.py` — berie metadáta z ITMS21 API (sparse data)
- `scraper/main.py cmd_embed()` — extrahuje text z príloh, chunkuje, embeduje
- `scraper/extractor/classifier.py` — klasifikuje dokumenty, ale **klasifikácia beží na základe filename + content**, nie po rozbalení ZIP
- `scraper/db.py` — má `save_attributes()` a `get_attributes()` metódy (fungujú)
- `grant_call_attributes` tabuľka existuje v DB (35 záznamov z Week 1)

## Čo treba zmeniť

### 1. Nový modul: `scraper/extractor/attribute_extractor.py`

Extrahuje štruktúrované atribúty z klasifikovaných dokumentov (hlavne `main` a `conditions` typy).

**Vstup:** List[ExtractedDocument] s doc_type
**Výstup:** Dict[str, str] — key-value atribúty

**Povinné atribúty na extrakciu (z PRD DE-008):**
- `kod_vyzvy` — kód výzvy (napr. PSK-SIEA-006-2024-DV-FST)
- `datum_vyhlasenia` — dátum vyhlásenia výzvy
- `deadline` — termín podania žiadostí
- `celkova_alokacia` — celková finančná alokácia (EUR)
- `poskytovatel` — poskytovateľ (ministerstvo/agentúra)
- `nazov_programu` — názov programu (napr. Program Slovensko)
- `specificke_ciele` — špecifické ciele
- `opravneni_ziadatelia` — oprávnení žiadatelia
- `opravnene_aktivity` — oprávnené aktivity
- `opravnene_uzemie` — oprávnené územie
- `miera_spolufinancovania` — miera spolufinancovania (%)
- `min_prispevok` — minimálny príspevok
- `max_prispevok` — maximálny príspevok

**Extrakčná stratégia:**
1. **Regex-first:** Pre kód výzvy, dátumy, sumy — regex na celom texte
2. **GPT-4o-mini fallback:** Pre zložitejšie atribúty (oprávnení žiadatelia, aktivity) — structured extraction
3. **Náklady:** max ~$0.01 per výzva (GPT-4o-mini je lacný)

### 2. Úprava `scraper/main.py cmd_embed()`

Aktuálny flow:
```
attachments → extract_from_url → classify → chunk → embed
```

Nový flow:
```
attachments → extract_from_url → classify (po rozbalení ZIP!)
           → attribute_extractor (pre main/conditions docs)
           → update grant_calls_v2 (announced_at, total_allocation, atď.)
           → save_attributes (key-value pre detail)
           → chunk → embed
```

### 3. Úprava `scraper/extractor/classifier.py`

Problém: klasifikácia beží na `filename + text[:2000]`, ale pre ZIP prílohy filename je často UUID alebo generický ("dokument_12345").

Fix: Po rozbalení ZIP, klasifikovať **vnútorné súbory** (nie ZIP ako celok). Vnútorné súbory majú zmysluplnejšie názvy (napr. "Priloha_1_Form_ZoNFP.docx", "Výzva_PSK-SIEA-006.pdf").

### 4. Úprava `scraper/handlers/itms21.py`

- API dáta ostávajú ako **fallback** (ak attachment extraction zlyhá)
- Ale primárny zdroj pre atribúty sú PDF prílohy
- `parse_call_detail()` vracia atribúty z API, tie sa potom **mergnú** s atribútmi z PDF (PDF má prednosť)

### 5. Update grant_calls_v2 z extrahovaných atribútov

Po extrakcii atribútov z PDF, updatnúť priamo v DB:
- `announced_at` ← `datum_vyhlasenia` (ak nájdený)
- `total_allocation` ← `celkova_alokacia` (ak nájdená)
- `deadline_at` ← `deadline` (ak nájdený)
- `provider` ← `poskytovatel` (ak nájdený)

Nová metóda v `db.py`: `update_grant_call(call_id, data_dict)` — PATCH operácia

## Task List

| # | Task | Popis | Odhad |
|---|------|-------|-------|
| T1 | `attribute_extractor.py` | Nový modul: regex + GPT-4o-mini extraction | 2h |
| T2 | Update `classifier.py` | Klasifikácia po ZIP rozbalení (vnútorné súbory) | 30min |
| T3 | Update `cmd_embed()` v `main.py` | Nový flow: extract → classify → attributes → chunk → embed | 1h |
| T4 | Nová metóda `db.update_grant_call()` | PATCH grant_calls_v2 z extrahovaných atribútov | 15min |
| T5 | Merge logic (API + PDF attributes) | PDF má prednosť, API je fallback | 30min |
| T6 | Testy na 3 výzvach (11, 45, 50) | Overenie správnosti extrakcie | 30min |

## Validačná stratégia

Po implementácii spustím:
```bash
python3 -m scraper.main embed --call-id 11 --force
python3 -m scraper.main embed --call-id 45 --force
python3 -m scraper.main embed --call-id 50 --force
```

Potom porovnám extrahované atribúty s referenčnými hodnotami z E2E testu:
- Výzva 11: alokácia 15 828 201 €, kód PSK-SIEA-006-2024-DV-FST
- Výzva 45: alokácia 38 000 000 €, kód PSK-MZP-016-2024-DV-EFRR
- Výzva 50: alokácia 91 507 483 €, kód PSK-MZP-002-2023-DV-KF

## Constraints

- `text-embedding-3-large` (3072 dim) — musí ostať konzistentné
- GPT-4o-mini pre extraction — max $0.01/výzva
- Fallback: ak GPT extraction zlyhá, regex výsledky stačia
- Nezmeniť existujúci chunking/embedding flow — len pridať attribute extraction krok pred ním

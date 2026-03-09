# Plan: Envirofond Handler — Nový zdroj výziev

## Cieľ

Pridať Envirofond (envirofond.sk) ako druhý zdroj grantových výziev.
Envirofond nemá API, len WordPress stránku s PDF prílohami.

## Kontext

- **Web:** https://envirofond.sk
- **Výzvy:** https://envirofond.sk/aktualne-vyzva-a-specifikacie/
- **Projekt:** /home/clawd/Projects/grant-viewer-saas (branch: saas-refactor)
- **Existujúci handler:** scraper/handlers/itms21.py (referencia)

## Štruktúra Envirofondu

### Aktuálne výzvy (2026)
| Oblasť | Názov | URL | Deadline |
|--------|-------|-----|----------|
| B | Vody | https://envirofond.sk/vody-vyzva-c-b1-2026/ | 13.04.2026 |
| C | Odpady | https://envirofond.sk/odpady-2026/ | 13.04.2026 |
| E | Enviro výchova | https://envirofond.sk/environmentalna-vychova-vzdelavanie-a-propagacia-2026/ | 13.04.2026 |
| L | Energetická účinnosť | https://envirofond.sk/zvysovanie-energetickej-ucinnosti-l-2026/ | 13.04.2026 |
| - | Mimoriadna podpora | https://envirofond.sk/mimoriadna/ | otvorená |
| - | Havárie | https://envirofond.sk/havarie/ | otvorená |
| - | Úvery | https://envirofond.sk/uvery-2/ | otvorená |

### Štruktúra stránky výzvy
Každá stránka výzvy obsahuje:
1. Názov a deadline (v HTML texte)
2. PDF prílohy (wp-content/uploads/):
   - **Výzva** alebo **Špecifikácia** (hlavný dokument s podmienkami)
   - **Príručka pre žiadateľa** (Príloha č. 1)
   - **Hodnotiace kritériá** (Príloha č. 2)
   - **Vzory** (uznesenie, vyjadrenie)
   - **Usmernenia** (aktualizácie)

### Štruktúra PDF (konzistentná pre všetky oblasti)
1. Súvisiace právne predpisy
2. Vymedzenie pojmov a skratiek
3. Formálne náležitosti (oprávnené obdobie, max dotácia, spolufinancovanie)
4. Oprávnení žiadatelia
5. Oprávnené aktivity
6. Prílohy k žiadosti

### PDF URL pattern
Hlavné dokumenty sú na:
```
https://envirofond.sk/wp-content/uploads/YYYY/MM/<filename>.pdf
```
Napr:
- Vyzva-B-1-rok-2026.pdf
- Specifikacia_oblast-C_2026.pdf
- Specifikacia_oblast-L_2026_aktualizacia_270226.pdf
- Priloha-c.-1_Prirucka-pre-ziadatela_oblast-L_2026_aktualizacia.pdf
- Priloha-c.-2_Hodnotiace-kriteria_oblast-C_2026.pdf

### Kľúčový rozdiel oproti ITMS21
- **ITMS21:** REST API → JSON → metadata + PDF prílohy z API
- **Envirofond:** HTML scraping → text + PDF URLs z `<a href="...pdf">`
- Envirofond nemá štruktúrované metadáta (title, announced_at, atď. treba extrahovať z HTML/PDF)

## TASK-001: Envirofond Handler

### Nový súbor: `scraper/handlers/envirofond.py`

Implementuj handler podľa BaseHandler interface (pozri `scraper/handlers/base.py`):

```python
class EnvirofondHandler(BaseHandler):
    def scrape_calls(self, limit=50) -> List[GrantCall]:
        # 1. Fetchni hlavnú stránku výziev
        # 2. Parsuj HTML tabuľku (Od, Do, Stav, názov, URL)
        # 3. Pre každú výzvu: fetchni detail stránku → extrahuj PDF linky
        # 4. Vráť list GrantCall objektov
        
    def get_attachments(self, call_url: str) -> List[Attachment]:
        # Fetchni stránku výzvy, parsuj <a> linky na PDF/DOCX
```

### Scraping logika

1. **Hlavná stránka** (`/aktualne-vyzva-a-specifikacie/`):
   - Parsuj tabuľku s výzvami (BeautifulSoup alebo regex)
   - Extrahuj: názov, URL detail stránky, dátum od, dátum do, stav

2. **Detail stránka** (napr. `/vody-vyzva-c-b1-2026/`):
   - Nájdi všetky `<a href="...pdf">` a `<a href="...docx">`
   - Filtruj: ignoruj generické PDF (GDPR, manuál)
   - Klasifikuj: Výzva/Špecifikácia = main, Príručka = conditions, Kritériá = criteria

3. **Metadata z HTML:**
   - title: z `<h5>` alebo `<title>` tagu
   - announced_at: z "Od:" v tabuľke
   - deadline_at: z "Do:" v tabuľke
   - provider: vždy "Environmentálny fond"
   - source: "envirofond.sk"
   - status: z "Stav:" v tabuľke

### Filtre pre PDF
Ignorovať tieto PDF (generické, na každej stránke):
- Pouzivatelsky-manual.pdf
- Informacie_GDPR_EF.pdf

## TASK-002: Registrácia v CLI

V `scraper/main.py`:
- Pridaj `--source envirofond` do `cmd_scrape()`
- Import a použitie `EnvirofondHandler`

## TASK-003: Classifier update

V `scraper/extractor/classifier.py`:
- Pridaj Envirofond-špecifické keywords pre klasifikáciu:
  - "Špecifikácia činností" → main
  - "Príručka pre žiadateľa" → conditions
  - "Hodnotiace kritériá" → criteria
  - "Usmernenie" → main (update)
  - "Vzor uznesenia" → other

## TASK-004: Test — Scrape + Embed

1. `python3 -m scraper.main scrape --source envirofond --limit 10`
2. Vyber 2 výzvy, spusti embed: `python3 -m scraper.main embed --call-id X`
3. Spusti enrich: `python3 -m scraper.main enrich --call-id X`
4. Test search: 5 otázok relevantných pre Envirofond

### Testovacie otázky
1. Aká je maximálna výška dotácie pre oblasť L?
2. Kto sú oprávnení žiadatelia pre vodovody?
3. Aké sú oprávnené aktivity pre odpady?
4. Aký je deadline na podanie žiadosti?
5. Aké sú hodnotiace kritériá pre energetickú účinnosť?

## Technické poznámky

- BeautifulSoup4 je potrebný: `pip3 install beautifulsoup4` (ak nie je)
- HTML na Envirofonde je WordPress, pomerne jednoduché
- Cookie consent wall: treba poslať cookie header `cookie_notice_accepted=true`
- Niektoré stránky majú aj archívne výzvy (MoF), tie zatiaľ ignorujeme

## Výstup

- Nový handler `scraper/handlers/envirofond.py`
- Aktualizovaný `scraper/main.py` a `scraper/extractor/classifier.py`
- Min 2 výzvy embedované a vyhľadateľné
- Výsledky testu v `docs/ENVIROFOND_TEST_RESULTS.md`

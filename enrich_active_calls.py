#!/usr/bin/env python3
"""
Enrich active grant calls with detailed structured data.

Uses UniversalExtractor for document classification + text extraction,
then AI (GPT-4o-mini) for structured data parsing.
Saves to grant_call_attributes (used by frontend + PDF report).

Supports all sources via UniversalExtractor handlers.
"""

import os
import sys
import json
import re
import time
import psycopg2
from psycopg2.extras import RealDictCursor
from dotenv import load_dotenv

load_dotenv()

DB_URL = os.getenv('DATABASE_URL',
    'postgresql://postgres.kapgabgnezcurmgcrvif:H3s10D0FrantiskA5,@aws-1-eu-central-1.pooler.supabase.com:6543/postgres')

from openai import OpenAI
openai_client = OpenAI(api_key=os.getenv('OPENAI_API_KEY'))

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from universal_extractor import UniversalExtractor, SourceType


def get_db():
    for attempt in range(3):
        try:
            return psycopg2.connect(DB_URL)
        except Exception:
            if attempt < 2:
                time.sleep(2 ** attempt)
            else:
                raise

def get_active_calls():
    conn = get_db()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("""
        SELECT gc.id, gc.title, gc.source, gc.call_url, gc.provider,
               gc.announced_at, gc.deadline_at, gc.total_allocation,
               gc.eligible_applicants, gc.status,
               COALESCE(
                   json_agg(json_build_object(
                       'name', gca.name, 'url', gca.url, 'file_type', gca.file_type
                   )) FILTER (WHERE gca.id IS NOT NULL),
                   '[]'::json
               ) as attachments,
               (SELECT COUNT(*) FROM grant_call_attributes a
                WHERE a.grant_call_id = gc.id
                AND a.key IN ('Cieľ výzvy', 'Oprávnené územie', 'Spoluúčasť', 'Max. podpora na projekt')
               ) as detail_attrs_count
        FROM grant_calls_v2 gc
        LEFT JOIN grant_call_attachments gca ON gca.grant_call_id = gc.id
        WHERE gc.status IN ('Otvorená', 'Vyhlásená', 'Plánovaná')
        GROUP BY gc.id
        ORDER BY gc.source
    """)
    calls = cur.fetchall()
    conn.close()
    return calls

def save_attributes(call_id, attrs_dict):
    conn = get_db()
    cur = conn.cursor()
    saved = 0
    for key, value in attrs_dict.items():
        if not value or not str(value).strip():
            continue
        value_str = str(value).strip()
        cur.execute("DELETE FROM grant_call_attributes WHERE grant_call_id = %s AND key = %s",
                    (call_id, key))
        cur.execute("INSERT INTO grant_call_attributes (grant_call_id, key, value) VALUES (%s, %s, %s)",
                    (call_id, key, value_str))
        saved += 1
    conn.commit()
    conn.close()
    print(f"    Saved {saved} attributes")


EXTRACTION_PROMPT = """Analyzuj text grantovej výzvy a extrahuj štruktúrované údaje.

Názov výzvy: {title}
Zdroj: {source}

Text dokumentu:
{text}

Vráť VÝHRADNE tento JSON (bez markdown, bez komentárov):
{{
    "ciel_vyzvy": "podrobný popis cieľa výzvy (2-5 viet)",
    "kod_vyzvy": "kód výzvy ak je uvedený, inak null",
    "alokacia": "celková alokácia výzvy ako text (napr. '57 000 000 EUR')",
    "max_podpora_projekt": "maximálna výška podpory na 1 projekt ak je uvedená, inak null",
    "min_podpora_projekt": "minimálna výška podpory na 1 projekt ak je uvedená, inak null",
    "opravnene_uzemie": "oprávnené územie (napr. 'celá SR', 'Bratislavský kraj') alebo null",
    "spoluucast": "miera spoluúčasti žiadateľa (napr. '0%', '5%', '10-15%') alebo null",
    "opravneny_ziadatel": "podrobný popis oprávnených žiadateľov",
    "opravnene_aktivity": "zoznam oprávnených aktivít/činností ak sú uvedené, inak null",
    "opravnene_vydavky": "zoznam oprávnených výdavkov/nákladov ak sú uvedené, inak null",
    "kriteria_vyberu": "hodnotiace kritériá ak sú uvedené, inak null",
    "casova_opravnenost": "časová oprávnenosť realizácie projektu ak je uvedená, inak null",
    "predkladanie": "spôsob a termín predkladania žiadostí ak je uvedený, inak null",
    "dalsie_podmienky": "ďalšie dôležité podmienky, obmedzenia alebo informácie"
}}

Pravidlá:
- Extrahuj LEN informácie ktoré sú EXPLICITNE uvedené v texte
- Pre chýbajúce informácie použi null
- Texty píš v slovenčine
- Pre oprávneného žiadateľa buď čo najpodrobnejší
- Pre oprávnené aktivity a výdavky vymenuj konkrétne položky ak sú v texte"""

ATTR_MAP = {
    'ciel_vyzvy': 'Cieľ výzvy',
    'kod_vyzvy': 'Kód výzvy',
    'alokacia': 'Celková alokácia',
    'max_podpora_projekt': 'Max. podpora na projekt',
    'min_podpora_projekt': 'Min. podpora na projekt',
    'opravnene_uzemie': 'Oprávnené územie',
    'spoluucast': 'Spoluúčasť',
    'opravneny_ziadatel': 'Oprávnení žiadatelia (detailné)',
    'opravnene_aktivity': 'Oprávnené aktivity',
    'opravnene_vydavky': 'Oprávnené výdavky',
    'kriteria_vyberu': 'Kritériá výberu',
    'casova_opravnenost': 'Časová oprávnenosť',
    'predkladanie': 'Predkladanie žiadostí',
    'dalsie_podmienky': 'Ďalšie podmienky',
}

def ai_extract(text, title, source):
    max_len = 25000
    truncated = text[:max_len] if len(text) > max_len else text
    prompt = EXTRACTION_PROMPT.format(title=title, source=source, text=truncated)
    try:
        response = openai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "Si analytik grantových výziev. Extrahuj štruktúrované údaje z textu výzvy. Odpovedaj VÝHRADNE v JSON formáte."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.1,
            max_tokens=3000
        )
        result_text = response.choices[0].message.content.strip()
        if result_text.startswith('```'):
            result_text = re.sub(r'^```\w*\n?', '', result_text)
            result_text = re.sub(r'\n?```$', '', result_text)
        return json.loads(result_text)
    except Exception as e:
        print(f"    AI extraction error: {e}")
        return {}


def process_call(call, extractor):
    call_id = call['id']
    title = call['title']
    source = call['source']
    attachments = call['attachments'] if isinstance(call['attachments'], list) else json.loads(call['attachments'])

    print(f"\n{'='*60}")
    print(f"  {title[:80]}")
    print(f"  Source: {source} | Attachments: {len(attachments)} | Existing detail attrs: {call['detail_attrs_count']}")

    if call['detail_attrs_count'] >= 4:
        print(f"  SKIP: Already has {call['detail_attrs_count']} detail attributes")
        return

    # Use UniversalExtractor to detect source and get handler
    source_type = extractor.detect_source_by_name(source)
    handler = extractor.get_handler(source_type)

    if not handler:
        print(f"  WARNING: No handler for source '{source}' (type: {source_type})")
        return

    print(f"  Handler: {handler.__class__.__name__} (type: {source_type.value})")

    # Build URL list: attachment URLs + call_url
    urls = [a['url'] for a in attachments if a.get('url')]
    if call.get('call_url') and call['call_url'] not in urls:
        urls.append(call['call_url'])

    if not urls:
        print(f"  WARNING: No URLs to process")
        return

    # Classify and extract using handler
    docs = handler.classify_documents(urls)
    print(f"  Classified {len(docs)} documents")

    combined_text = ""
    for doc in docs:
        if doc.doc_type == 'skip':
            continue
        print(f"    Extracting: {doc.url[:80]}...")
        text, error = handler.download_and_extract(doc.url)
        if error:
            print(f"    Error: {error}")
        if text and len(text) > 200:
            combined_text += f"\n\n{text}"
            if doc.doc_type == 'main' and len(text) > 5000:
                break

    if not combined_text or len(combined_text) < 300:
        print(f"  WARNING: Insufficient text ({len(combined_text) if combined_text else 0} chars)")
        return

    # Structure analysis
    structure = handler.analyze_structure(combined_text)
    print(f"  Text: {len(combined_text)} chars | Structure: {structure}")

    # AI extraction
    print(f"  Running AI extraction...")
    extracted = ai_extract(combined_text, title, source)
    if not extracted:
        print(f"  ERROR: AI extraction returned empty")
        return

    attrs = {}
    for json_key, attr_key in ATTR_MAP.items():
        val = extracted.get(json_key)
        if val and val != 'null' and str(val).strip():
            attrs[attr_key] = str(val)

    if attrs:
        print(f"  Extracted {len(attrs)} attributes: {list(attrs.keys())}")
        save_attributes(call_id, attrs)
    else:
        print(f"  WARNING: No attributes extracted")


def main():
    print("=" * 60)
    print("Grant Call Enrichment (UniversalExtractor)")
    print("=" * 60)

    extractor = UniversalExtractor()
    calls = get_active_calls()
    print(f"\nFound {len(calls)} active calls\n")

    for call in calls:
        try:
            process_call(call, extractor)
        except Exception as e:
            print(f"  ERROR processing {call['title'][:50]}: {e}")
            import traceback
            traceback.print_exc()

    print(f"\n{'='*60}")
    print("Done!")

if __name__ == "__main__":
    main()

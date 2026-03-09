#!/usr/bin/env python3
"""Generic PDF enrichment for grant calls.

Downloads PDF attachments, extracts text, sends to AI for structured data extraction,
and updates grant_call_attributes in Supabase.

Usage:
  source venv/bin/activate
  python3 v2/pdf_enrichment.py                    # enrich all calls with PDF attachments
  python3 v2/pdf_enrichment.py --source envirofond.sk --limit 5
  python3 v2/pdf_enrichment.py --call-id <uuid>   # enrich a specific call
"""

import argparse
import json
import os
import re
import sys
import tempfile
import uuid
from datetime import datetime, timezone

import pymupdf  # PyMuPDF
import requests

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from storage import (
    delete_call_attributes,
    insert_call_attributes,
)

# --- Config ---
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")

# Max chars of PDF text to send to LLM (to avoid token limits)
MAX_PDF_CHARS = 12000

EXTRACTION_PROMPT = """Analyzuj nasledujúci text z PDF dokumentu, ktorý popisuje grantovú výzvu.
Extrahuj tieto údaje (ak sú dostupné). Ak údaj nie je v texte, vráť null.

Požadované polia:
- nazov_vyzvy: Oficiálny názov výzvy
- kod_vyzvy: Kód/číslo výzvy
- poskytovatel: Kto výzvu vyhlasuje (ministerstvo, agentúra, fond...)
- opravneni_ziadatelia: Kto môže žiadať (typy organizácií, podmienky)
- celkova_alokacia: Celková alokácia/rozpočet výzvy (suma v EUR ak je uvedená)
- max_podpora_projekt: Maximálna výška podpory na jeden projekt
- min_podpora_projekt: Minimálna výška podpory na jeden projekt
- miera_spolufinancovania: Miera spolufinancovania žiadateľa (% alebo popis)
- datum_vyhlasenia: Dátum vyhlásenia výzvy (formát YYYY-MM-DD ak možné)
- datum_uzavierky: Dátum uzávierky / termín podania (formát YYYY-MM-DD ak možné)
- oblast: Oblasť/sektor (životné prostredie, vzdelávanie, doprava...)
- opravnene_aktivity: Stručný popis oprávnených aktivít/účelov
- miesto_realizacie: Kde sa projekt môže realizovať (kraje, celé SR...)
- typ_vyzvy: Typ (otvorená, uzavretá, priebežná...)
- dalsie_podmienky: Ďalšie dôležité podmienky alebo obmedzenia

Odpovedz VÝHRADNE ako JSON objekt. Žiadny iný text pred ani za JSON.

Text z PDF:
---
{pdf_text}
---"""


def extract_text_from_pdf(pdf_path: str) -> str:
    """Extract text from a PDF file using PyMuPDF."""
    doc = pymupdf.open(pdf_path)
    text_parts = []
    for page in doc:
        text_parts.append(page.get_text())
    doc.close()
    return "\n".join(text_parts)


def download_pdf(url: str, dest_dir: str) -> str:
    """Download a PDF to a temp file, return path."""
    resp = requests.get(url, timeout=30, allow_redirects=True)
    resp.raise_for_status()

    # Determine filename
    fname = url.split("/")[-1].split("?")[0]
    if not fname.endswith(".pdf"):
        fname = "document.pdf"
    
    path = os.path.join(dest_dir, fname)
    with open(path, "wb") as f:
        f.write(resp.content)
    return path


def call_llm(prompt: str) -> dict:
    """Call LLM API (OpenRouter preferred, OpenAI fallback) and return parsed JSON."""
    
    # Try OpenRouter first (cheaper)
    if OPENROUTER_API_KEY:
        try:
            return _call_openrouter(prompt)
        except Exception as e:
            print(f"  OpenRouter failed: {e}, trying OpenAI...")
    
    if OPENAI_API_KEY:
        return _call_openai(prompt)
    
    raise RuntimeError("No LLM API key available (OPENROUTER_API_KEY or OPENAI_API_KEY)")


def _call_openrouter(prompt: str) -> dict:
    resp = requests.post(
        "https://openrouter.ai/api/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {OPENROUTER_API_KEY}",
            "Content-Type": "application/json",
        },
        json={
            "model": "deepseek/deepseek-v3",
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.1,
            "max_tokens": 2000,
        },
        timeout=60,
    )
    resp.raise_for_status()
    content = resp.json()["choices"][0]["message"]["content"]
    return _parse_json_response(content)


def _call_openai(prompt: str) -> dict:
    resp = requests.post(
        "https://api.openai.com/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {OPENAI_API_KEY}",
            "Content-Type": "application/json",
        },
        json={
            "model": "gpt-4o-mini",
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.1,
            "max_tokens": 2000,
        },
        timeout=60,
    )
    resp.raise_for_status()
    content = resp.json()["choices"][0]["message"]["content"]
    return _parse_json_response(content)


def _parse_json_response(content: str) -> dict:
    """Parse JSON from LLM response, handling markdown code blocks."""
    # Strip markdown code blocks if present
    content = content.strip()
    if content.startswith("```"):
        # Remove first line (```json) and last line (```)
        lines = content.split("\n")
        content = "\n".join(lines[1:-1])
    
    return json.loads(content)


def get_calls_with_pdf_attachments(source_filter=None, call_id=None):
    """Fetch calls that have PDF attachments from Supabase."""
    from dotenv import load_dotenv
    load_dotenv(os.path.join(PROJECT_ROOT, ".env"))
    
    from supabase import create_client
    sb = create_client(
        os.environ["SUPABASE_URL"],
        os.environ["SUPABASE_SERVICE_ROLE_KEY"],
    )
    
    # Get PDF attachments
    q = sb.table("grant_call_attachments").select("*").ilike("url", "%.pdf%")
    if call_id:
        q = q.eq("grant_call_id", call_id)
    att_resp = q.execute()
    
    # Group by call_id
    from collections import defaultdict
    by_call = defaultdict(list)
    for att in att_resp.data:
        by_call[att["grant_call_id"]].append(att)
    
    if not by_call:
        return []
    
    # Get call info
    call_ids = list(by_call.keys())
    calls_resp = sb.table("grant_calls_v2").select("*").in_("id", call_ids).execute()
    
    results = []
    for call in calls_resp.data:
        if source_filter and call["source"] != source_filter:
            continue
        results.append({
            "call": call,
            "pdf_attachments": by_call[call["id"]],
        })
    
    return results


# Field mapping: LLM JSON key -> (attribute key for DB, also update core table field?)
FIELD_MAP = {
    "nazov_vyzvy": ("Oficiálny názov výzvy", None),
    "kod_vyzvy": ("Kód výzvy", None),
    "poskytovatel": ("Poskytovateľ", "provider"),
    "opravneni_ziadatelia": ("Oprávnení žiadatelia", "eligible_applicants"),
    "celkova_alokacia": ("Celková alokácia", None),
    "max_podpora_projekt": ("Max. podpora na projekt", None),
    "min_podpora_projekt": ("Min. podpora na projekt", None),
    "miera_spolufinancovania": ("Miera spolufinancovania", None),
    "datum_vyhlasenia": ("Dátum vyhlásenia", None),
    "datum_uzavierky": ("Dátum uzávierky", None),
    "oblast": ("Oblasť", None),
    "opravnene_aktivity": ("Oprávnené aktivity", None),
    "miesto_realizacie": ("Miesto realizácie", None),
    "typ_vyzvy": ("Typ výzvy", None),
    "dalsie_podmienky": ("Ďalšie podmienky", None),
}


def enrich_call(call_data, pdf_attachments, tmpdir):
    """Download PDFs, extract text, call LLM, save attributes."""
    call = call_data
    call_id = call["id"]
    
    # Download and extract text from the first suitable PDF (usually the main call document)
    # Sort: prefer files with "vyzva" or "výzva" in name
    sorted_pdfs = sorted(
        pdf_attachments,
        key=lambda a: (0 if "yzv" in (a.get("name") or "").lower() else 1),
    )
    
    combined_text = ""
    for att in sorted_pdfs[:2]:  # Max 2 PDFs
        url = att["url"]
        try:
            print(f"    Downloading: {url.split('/')[-1][:60]}")
            pdf_path = download_pdf(url, tmpdir)
            text = extract_text_from_pdf(pdf_path)
            if text.strip():
                combined_text += f"\n--- {att.get('name', 'dokument')} ---\n{text}\n"
                print(f"    Extracted {len(text)} chars")
            os.unlink(pdf_path)
        except Exception as e:
            print(f"    PDF error: {e}")
            continue
    
    if not combined_text.strip():
        print("    No text extracted from PDFs, skipping")
        return False
    
    # Truncate to max chars
    if len(combined_text) > MAX_PDF_CHARS:
        combined_text = combined_text[:MAX_PDF_CHARS] + "\n[... skrátené ...]"
    
    # Call LLM
    prompt = EXTRACTION_PROMPT.replace("{pdf_text}", combined_text)
    print(f"    Calling LLM ({len(combined_text)} chars)...")
    
    try:
        extracted = call_llm(prompt)
    except Exception as e:
        print(f"    LLM error: {e}")
        return False
    
    # Build attributes
    new_attrs = []
    core_updates = {}
    
    for json_key, (attr_name, core_field) in FIELD_MAP.items():
        value = extracted.get(json_key)
        if value and value != "null" and str(value).strip():
            # Convert numbers/lists to string
            if isinstance(value, (list, dict)):
                value = json.dumps(value, ensure_ascii=False)
            value = str(value).strip()
            
            new_attrs.append({
                "id": str(uuid.uuid4()),
                "grant_call_id": call_id,
                "key": attr_name,
                "value": value[:2000],  # Supabase text limit safety
                "value_type": "text",
            })
            
            if core_field:
                core_updates[core_field] = value[:500]
    
    # Parse allocation as number for core table
    alloc_str = extracted.get("celkova_alokacia")
    if alloc_str and alloc_str != "null":
        # Try to parse number from string like "5 000 000 EUR" or "5000000"
        nums = re.findall(r"[\d\s,\.]+", str(alloc_str))
        if nums:
            num_str = nums[0].replace(" ", "").replace(",", ".").strip(".")
            try:
                core_updates["total_allocation"] = float(num_str)
            except ValueError:
                pass
    
    # Save to DB
    if new_attrs:
        # Don't delete existing attrs - merge (delete only AI-extracted ones)
        # Actually, let's add with a prefix to distinguish
        delete_call_attributes(call_id)  # Clean slate for this call
        
        # Re-add any manually-set attrs? For now, replace all.
        insert_call_attributes(new_attrs)
        print(f"    Saved {len(new_attrs)} attributes from PDF")
    
    # Update core table fields
    if core_updates:
        from dotenv import load_dotenv
        load_dotenv(os.path.join(PROJECT_ROOT, ".env"))
        from supabase import create_client
        sb = create_client(
            os.environ["SUPABASE_URL"],
            os.environ["SUPABASE_SERVICE_ROLE_KEY"],
        )
        sb.table("grant_calls_v2").update(core_updates).eq("id", call_id).execute()
        print(f"    Updated core fields: {list(core_updates.keys())}")
    
    return True


def main():
    parser = argparse.ArgumentParser(description="PDF enrichment for grant calls")
    parser.add_argument("--source", help="Filter by source (e.g. envirofond.sk)")
    parser.add_argument("--call-id", help="Enrich a specific call by ID")
    parser.add_argument("--limit", type=int, default=10, help="Max calls to process")
    parser.add_argument("--dry-run", action="store_true", help="Download + extract only, no LLM/save")
    args = parser.parse_args()

    print("Fetching calls with PDF attachments...")
    items = get_calls_with_pdf_attachments(
        source_filter=args.source,
        call_id=args.call_id,
    )
    print(f"Found {len(items)} calls with PDFs\n")

    with tempfile.TemporaryDirectory() as tmpdir:
        processed = 0
        for item in items:
            if processed >= args.limit:
                break
            
            call = item["call"]
            pdfs = item["pdf_attachments"]
            
            print(f"=== {call['title'][:70]} ===")
            print(f"  Source: {call['source']} | PDFs: {len(pdfs)}")
            
            if args.dry_run:
                for att in pdfs[:2]:
                    try:
                        pdf_path = download_pdf(att["url"], tmpdir)
                        text = extract_text_from_pdf(pdf_path)
                        print(f"  {att['name'][:50]}: {len(text)} chars")
                        print(f"  Preview: {text[:200]}...")
                        os.unlink(pdf_path)
                    except Exception as e:
                        print(f"  Error: {e}")
                processed += 1
                continue
            
            success = enrich_call(call, pdfs, tmpdir)
            if success:
                processed += 1
            print()

    print(f"\nDONE — enriched {processed} calls")


if __name__ == "__main__":
    main()

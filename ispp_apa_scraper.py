#!/usr/bin/env python3
"""ISPP APA scraper — uses public-api.apa.sk to fetch PPA grant calls (SP SPP 2023-2027)."""

import os
import re
import sys
from datetime import datetime, timezone

import requests
from bs4 import BeautifulSoup

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from storage import (
    delete_call_attributes,
    delete_call_attachments,
    insert_call_attributes,
    insert_call_attachments,
    upsert_grant_calls_v2,
)

API_BASE = "https://public-api.apa.sk"
LIST_URL = f"{API_BASE}/public/vyzva"
DETAIL_URL = f"{API_BASE}/public/vyzva/{{vyzvaId}}"
ATTACHMENTS_URL = f"{API_BASE}/public/vyzva/{{vyzvaId}}/prilohy/{{cisloPrilohy}}/dokumenty"
FULL_TEXT_URL = f"{API_BASE}/public/vyzva/{{vyzvaId}}/plne-znenie/dokumenty"
DOC_CONTENT_URL = f"{API_BASE}/public/vyzva/{{vyzvaId}}/plne-znenie/dokumenty/{{dokumentId}}/content"
PORTAL_URL = "https://ispp.apa.sk/app/vyzvy/{vyzvaId}"

STATUS_MAP = {
    "ZVEREJNENA": "Otvorená",
    "POZASTAVENA": "Pozastavená",
    "ZRUSENA": "Zrušená",
}


def html_to_text(html_str):
    """Strip HTML tags, return plain text."""
    if not html_str:
        return None
    return BeautifulSoup(html_str, "html.parser").get_text(" ", strip=True)[:5000]


def fetch_list():
    """Fetch list of all calls from the API."""
    resp = requests.get(LIST_URL, timeout=15)
    resp.raise_for_status()
    data = resp.json()
    return data.get("content", data) if isinstance(data, dict) else data


def fetch_detail(vyzva_id):
    """Fetch full detail of a single call."""
    url = DETAIL_URL.format(vyzvaId=vyzva_id)
    resp = requests.get(url, timeout=15)
    resp.raise_for_status()
    return resp.json()


def fetch_attachments(vyzva_id, detail):
    """Collect all attachments (přílohy + plné znenie)."""
    attachments = []

    # Full text documents
    try:
        url = FULL_TEXT_URL.format(vyzvaId=vyzva_id)
        resp = requests.get(url, timeout=10)
        if resp.ok:
            docs = resp.json().get("content", [])
            for doc in docs:
                doc_id = doc.get("dokumentId")
                fmt = doc.get("format", "").lower()
                name = doc.get("originalFileName") or doc.get("nazov", "")
                download_url = f"{API_BASE}/public/vyzva/{vyzva_id}/plne-znenie/dokumenty/{doc_id}/content"
                attachments.append({"name": f"Plné znenie: {name}"[:500], "url": download_url, "file_type": fmt})
    except Exception as e:
        print(f"  Warning: could not fetch full text docs: {e}")

    # Numbered attachments from detail
    prilohy = detail.get("prilohaResponses", [])
    for pr in prilohy:
        cislo = pr.get("poradie")
        pr_name = pr.get("nazov", f"Príloha č. {cislo}")
        try:
            url = ATTACHMENTS_URL.format(vyzvaId=vyzva_id, cisloPrilohy=cislo)
            resp = requests.get(url, timeout=10)
            if resp.ok:
                docs = resp.json().get("content", [])
                for doc in docs:
                    doc_id = doc.get("dokumentId")
                    fmt = doc.get("format", "").lower()
                    fname = doc.get("originalFileName") or doc.get("nazov", "")
                    download_url = f"{API_BASE}/public/vyzva/{vyzva_id}/prilohy/{cislo}/dokumenty/{doc_id}/content"
                    attachments.append({
                        "name": f"{pr_name}: {fname}"[:500],
                        "url": download_url,
                        "file_type": fmt,
                    })
        except Exception as e:
            print(f"  Warning: could not fetch attachment {cislo}: {e}")

    return attachments


def parse_date(val):
    """Parse date string from API (YYYY-MM-DD or ISO datetime)."""
    if not val:
        return None
    # Already YYYY-MM-DD
    if re.match(r"^\d{4}-\d{2}-\d{2}$", val):
        return val
    # ISO datetime
    m = re.match(r"(\d{4}-\d{2}-\d{2})", val)
    return m.group(1) if m else None


def main():
    print("=" * 60)
    print("🌾 Scraping ISPP APA (public-api.apa.sk)...")
    print("=" * 60)

    calls_list = fetch_list()
    print(f"Found {len(calls_list)} calls in list")

    success = 0
    for item in calls_list:
        vyzva_id = item.get("vyzvaId")
        kod = item.get("kod", "")
        nazov = item.get("nazov", "")
        print(f"\n--- [{kod}] {nazov} ---")

        # Fetch detail
        try:
            detail = fetch_detail(vyzva_id)
        except Exception as e:
            print(f"  ERROR fetching detail: {e}")
            continue

        # Determine status
        stav = detail.get("stav", "ZVEREJNENA")
        # Check if deadline passed
        deadline_str = parse_date(detail.get("datumCasUzavretia") or detail.get("zoppmPodanieDo"))
        status = STATUS_MAP.get(stav, "Otvorená")
        if deadline_str:
            try:
                dl = datetime.strptime(deadline_str, "%Y-%m-%d")
                if dl < datetime.now():
                    status = "Uzavretá"
            except ValueError:
                pass

        call_url = PORTAL_URL.format(vyzvaId=vyzva_id)
        allocation = detail.get("sumVyskaProstriedkov")
        eligible = html_to_text(detail.get("opravneniZiadatelia"))

        # Build description from available fields
        desc_parts = []
        for field, label in [
            ("oblast", "Oblasť"),
            ("komponent", "Komponent"),
            ("opatrenie", "Opatrenie"),
            ("vyhlasenaNaZaklade", "Vyhlásená na základe"),
        ]:
            val = detail.get(field)
            if val:
                desc_parts.append(f"{label}: {val}")
        # Add HTML-based content
        for field in ["ineFormalneNalezitosti", "kriteriaHodnoteniaZoPPM", "sposobHodnoteniaZoPPM"]:
            txt = html_to_text(detail.get(field))
            if txt:
                desc_parts.append(txt)

        core = {
            "source": "ispp.apa.sk",
            "source_url": "https://ispp.apa.sk/app/vyzvy",
            "call_url": call_url,
            "title": f"{kod} — {nazov}"[:500],
            "announced_at": parse_date(detail.get("datumVyhlasenia")),
            "deadline_at": deadline_str,
            "provider": f"Pôdohospodárska platobná agentúra (PPA) — {detail.get('vykonavatel', 'PPA')}",
            "call_type": detail.get("uzavretieText") or "Výzva SP SPP 2023-2027",
            "total_allocation": allocation,
            "eligible_applicants": eligible[:2000] if eligible else None,
            "status": status,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }

        # Save core call
        saved = upsert_grant_calls_v2([core])
        call_id = saved[0]["id"] if saved else None
        if not call_id:
            print("  FAIL: could not save call")
            continue

        # Attributes
        delete_call_attributes(call_id)
        attrs = [
            {"grant_call_id": call_id, "key": "Vyhlasovateľ", "value": core["provider"], "value_type": "text"},
            {"grant_call_id": call_id, "key": "Kód výzvy", "value": kod, "value_type": "text"},
            {"grant_call_id": call_id, "key": "Oblasť", "value": detail.get("oblast", ""), "value_type": "text"},
            {"grant_call_id": call_id, "key": "Opatrenie", "value": detail.get("opatrenie", ""), "value_type": "text"},
        ]
        if detail.get("komponent"):
            attrs.append({"grant_call_id": call_id, "key": "Komponent", "value": detail["komponent"], "value_type": "text"})
        if detail.get("mieraSpolufinancovaniaUpresnenie"):
            attrs.append({"grant_call_id": call_id, "key": "Spolufinancovanie", "value": html_to_text(detail["mieraSpolufinancovaniaUpresnenie"])[:2000], "value_type": "text"})
        if desc_parts:
            attrs.append({"grant_call_id": call_id, "key": "Popis", "value": "\n".join(desc_parts)[:5000], "value_type": "text"})
        attrs = [a for a in attrs if a.get("value")]
        insert_call_attributes(attrs)

        # Attachments
        delete_call_attachments(call_id)
        attachments = fetch_attachments(vyzva_id, detail)
        att_payload = [
            {"grant_call_id": call_id, "name": a["name"][:500], "url": a["url"], "file_type": a.get("file_type")}
            for a in attachments if a.get("url")
        ]
        if att_payload:
            insert_call_attachments(att_payload)

        print(f"  ✅ Saved: call_id={call_id} status={status} alloc={allocation} attach={len(att_payload)}")
        success += 1

    print(f"\n{'=' * 60}")
    print(f"✅ DONE — {success}/{len(calls_list)} calls saved")
    print(f"{'=' * 60}")
    return success


if __name__ == "__main__":
    main()

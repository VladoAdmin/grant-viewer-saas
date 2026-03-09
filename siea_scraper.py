#!/usr/bin/env python3
"""SIEA scraper — scrapes calls from siea.sk/vyzvy/"""

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

URL = "https://www.siea.sk/strukturalne-fondy-eu/program-slovensko/vyzvy-implementovane-siea/"
BASE = "https://www.siea.sk"


def parse_date(text):
    if not text:
        return None
    m = re.search(r"(\d{1,2})\.\s*(\d{1,2})\.\s*(\d{4})", text)
    if m:
        return f"{int(m.group(3)):04d}-{int(m.group(2)):02d}-{int(m.group(1)):02d}"
    return None


def main():
    print("Scraping SIEA...")
    r = requests.get(URL, timeout=15)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")

    # Find H2 elements with call codes
    h2s = soup.find_all("h2")
    calls = []
    for h2 in h2s:
        code = h2.get_text(strip=True)
        if not re.match(r"PSK-SIEA-\d+", code):
            continue

        # Get content until next h2
        content_parts = []
        sibling = h2.find_next_sibling()
        while sibling and sibling.name != "h2":
            content_parts.append(sibling)
            sibling = sibling.find_next_sibling()

        text = " ".join(p.get_text(" ", strip=True) for p in content_parts)

        # Extract title from first paragraph
        first_p = content_parts[0].get_text(" ", strip=True) if content_parts else ""
        title = f"{code} — {first_p[:150]}" if first_p else code

        # Dates
        announced = parse_date(re.search(r"[Dd]átum vyhlásenia[^:]*:\s*(\d{1,2}\.\s*\d{1,2}\.\s*\d{4})", text).group(1)) if re.search(r"[Dd]átum vyhlásenia[^:]*:\s*(\d{1,2}\.\s*\d{1,2}\.\s*\d{4})", text) else None

        # Status from text
        if "uzavrela výzvu" in text.lower() or "uzatvorení výzvy" in text.lower():
            status = "Uzavretá"
        elif "otvorená" in text.lower():
            status = "Otvorená"
        else:
            status = "Otvorená"

        # Allocation
        alloc = None
        m = re.search(r"[Aa]lokácia[^.]*?([\d\s]+(?:\d{3}))\s*(?:EUR|eur|€)", text)
        if m:
            try:
                alloc = float(m.group(1).replace(" ", "").replace("\xa0", ""))
            except:
                pass

        # Attachments (PDF links)
        attachments = []
        for part in content_parts:
            for a in part.find_all("a", href=True):
                href = a["href"]
                if href.endswith((".pdf", ".zip", ".docx")):
                    full_url = href if href.startswith("http") else BASE + href
                    name = a.get_text(strip=True) or href.split("/")[-1]
                    ext = href.rsplit(".", 1)[-1].lower()
                    attachments.append({"name": name[:500], "url": full_url, "file_type": ext})

        core = {
            "source": "siea.sk",
            "source_url": URL,
            "call_url": URL + "#" + code,
            "title": title[:500],
            "announced_at": announced,
            "deadline_at": None,
            "provider": "Slovenská inovačná a energetická agentúra (SIEA)",
            "call_type": "Výzva z Programu Slovensko",
            "total_allocation": alloc,
            "eligible_applicants": None,
            "status": status,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }

        calls.append((core, attachments))

    success = 0
    for core, attachments in calls:
        print(f"\n=== {core['title'][:70]} ===")
        saved = upsert_grant_calls_v2([core])
        call_id = saved[0]["id"] if saved else None
        if not call_id:
            print("  FAIL: could not save")
            continue

        delete_call_attributes(call_id)
        delete_call_attachments(call_id)

        attrs = [
            {"grant_call_id": call_id, "key": "Vyhlasovateľ", "value": core["provider"], "value_type": "text"},
        ]
        if core.get("call_type"):
            attrs.append({"grant_call_id": call_id, "key": "Typ výzvy", "value": core["call_type"], "value_type": "text"})
        insert_call_attributes(attrs)

        att_payload = [
            {"grant_call_id": call_id, "name": a["name"][:500], "url": a["url"], "file_type": a.get("file_type")}
            for a in attachments if a.get("url")
        ]
        if att_payload:
            insert_call_attachments(att_payload)

        print(f"  Saved: call_id={call_id} status={core['status']} attach={len(att_payload)}")
        success += 1

    print(f"\nDONE — {success} calls saved")


if __name__ == "__main__":
    main()

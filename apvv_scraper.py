#!/usr/bin/env python3
"""APVV scraper — scrapes calls from apvv.sk (general + bilateral + research bilateral + multilateral).

Each year page has one call with details and PDF attachments.
"""

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

BASE = "https://www.apvv.sk"

# All known call pages (manually extracted from navigation)
CALL_PAGES = [
    # Všeobecné výzvy
    "/grantove-schemy/vseobecne-vyzvy/vv-2025.html",
    "/grantove-schemy/vseobecne-vyzvy/vv-2024.html",
    "/grantove-schemy/vseobecne-vyzvy/vv-mvp-2024.html",
    "/grantove-schemy/vseobecne-vyzvy/vv-2023.html",
    "/grantove-schemy/vseobecne-vyzvy/vv-2022.html",
    "/grantove-schemy/vseobecne-vyzvy/vv-2021.html",
    "/grantove-schemy/vseobecne-vyzvy/vv-2020.html",
    # Bilaterálne výzvy (recent ones)
    "/grantove-schemy/bilateralne-vyzvy/slovensko-bulharsko-2025.html",
    "/grantove-schemy/bilateralne-vyzvy/slovensko-ukrajina-2025.html",
    "/grantove-schemy/bilateralne-vyzvy/slovensko-mne-2025.html",
    "/grantove-schemy/bilateralne-vyzvy/slovensko-polsko-2025.html",
    "/grantove-schemy/bilateralne-vyzvy/slovensko-srbsko-2025.html",
    "/grantove-schemy/bilateralne-vyzvy/slovensko-francuzsko-2024.html",
    "/grantove-schemy/bilateralne-vyzvy/slovensko-madarsko-2024.html",
    "/grantove-schemy/bilateralne-vyzvy/slovensko-taiwan-2024.html",
    "/grantove-schemy/bilateralne-vyzvy/slovensko-rakusko-2023.html",
    "/grantove-schemy/bilateralne-vyzvy/slovensko-bulharsko-2023.html",
    "/grantove-schemy/bilateralne-vyzvy/slovensko-cina-2023.html",
    "/grantove-schemy/bilateralne-vyzvy/slovensko-srbsko-2023.html",
    "/grantove-schemy/bilateralne-vyzvy/slovensko-polsko-2023.html",
    "/grantove-schemy/bilateralne-vyzvy/slovensko-francuzsko-2022.html",
    # Výskumné bilaterálne
    "/grantove-schemy/vyskumne-bilateralne-vyzvy/slovensko-taiwan-rd-2024.html",
    "/grantove-schemy/vyskumne-bilateralne-vyzvy/slovensko-izrael-rd-2023.html",
    # Multilaterálne
    "/grantove-schemy/multilateralne-vyzvy/ds-fr-2024.html",
    "/grantove-schemy/multilateralne-vyzvy/ds-fr-2022.html",
    # Programy
    "/grantove-schemy/programy/pp-msca-2022.html",
]


def parse_date(text):
    """Parse 'DD. MM. YYYY' to ISO date."""
    if not text:
        return None
    m = re.search(r"(\d{1,2})\.\s*(\d{1,2})\.\s*(\d{4})", text)
    if m:
        return f"{int(m.group(3)):04d}-{int(m.group(2)):02d}-{int(m.group(1)):02d}"
    return None


def scrape_call_page(path):
    url = BASE + path
    try:
        r = requests.get(url, timeout=15)
        r.raise_for_status()
    except Exception as e:
        print(f"  FAIL fetching {url}: {e}")
        return None

    soup = BeautifulSoup(r.text, "html.parser")

    # Title from h1 or title tag
    h1 = soup.find("h1")
    title_tag = soup.find("title")
    title = None
    if h1:
        title = h1.get_text(strip=True)
    if not title and title_tag:
        title = title_tag.get_text(strip=True).replace("APVV | ", "")

    if not title:
        return None

    # Get main content text
    content_div = soup.find("div", class_="content") or soup.find("main") or soup.find("article") or soup
    text = content_div.get_text(" ", strip=True)

    # Extract dates
    announced = None
    deadline = None

    # Pattern: "Dátum vyhlásenia výzvy je DD. MM. YYYY"
    m = re.search(r"[Dd]átum vyhlásenia[^,]*?(\d{1,2}\.\s*\d{1,2}\.\s*\d{4})", text)
    if m:
        announced = parse_date(m.group(1))

    m = re.search(r"[Dd]átum ukončenia[^,]*?(\d{1,2}\.\s*\d{1,2}\.\s*\d{4})", text)
    if m:
        deadline = parse_date(m.group(1))

    # Determine call type from path
    if "vseobecne" in path:
        call_type = "Všeobecná výzva"
    elif "bilateralne" in path or "vyskumne-bilateralne" in path:
        call_type = "Bilaterálna výzva"
    elif "multilateralne" in path:
        call_type = "Multilaterálna výzva"
    elif "programy" in path:
        call_type = "Program"
    else:
        call_type = "Výzva"

    # Determine status
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if deadline and deadline < now:
        status = "Uzavretá"
    elif announced and announced <= now:
        status = "Otvorená"
    else:
        status = "Plánovaná"

    # Extract PDF attachments
    attachments = []
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if href.endswith((".pdf", ".docx", ".doc", ".odt", ".xlsx")):
            full_url = href if href.startswith("http") else BASE + href
            name = a.get_text(strip=True) or href.split("/")[-1]
            ext = href.rsplit(".", 1)[-1].lower()
            attachments.append({"name": name[:500], "url": full_url, "file_type": ext})

    # Allocation
    alloc = None
    m = re.search(r"(\d[\d\s\.,]+)\s*EUR", text)
    if m:
        try:
            val = m.group(1).replace(" ", "").replace("\xa0", "").replace(".", "").replace(",", ".")
            alloc = float(val)
        except:
            pass

    core = {
        "source": "apvv.sk",
        "source_url": "https://www.apvv.sk/grantove-schemy/vseobecne-vyzvy.html",
        "call_url": url,
        "title": f"APVV {title}"[:500],
        "announced_at": announced,
        "deadline_at": deadline,
        "provider": "Agentúra na podporu výskumu a vývoja (APVV)",
        "call_type": call_type,
        "total_allocation": alloc,
        "eligible_applicants": None,
        "status": status,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }

    return core, attachments


def save_call(core, attachments_raw):
    saved = upsert_grant_calls_v2([core])
    call_id = saved[0]["id"] if saved else None
    if not call_id:
        return None, 0, 0

    delete_call_attributes(call_id)
    delete_call_attachments(call_id)

    attrs = []
    if core.get("call_type"):
        attrs.append({"grant_call_id": call_id, "key": "Typ výzvy", "value": core["call_type"], "value_type": "text"})
    if core.get("provider"):
        attrs.append({"grant_call_id": call_id, "key": "Vyhlasovateľ", "value": core["provider"], "value_type": "text"})

    if attrs:
        insert_call_attributes(attrs)

    att_payload = []
    for a in attachments_raw:
        if a.get("url"):
            att_payload.append({
                "grant_call_id": call_id,
                "name": a.get("name", "")[:500],
                "url": a["url"],
                "file_type": a.get("file_type"),
            })
    if att_payload:
        insert_call_attachments(att_payload)

    return call_id, len(attrs), len(att_payload)


def main():
    print(f"Scraping APVV — {len(CALL_PAGES)} call pages...")
    success = 0
    failed = 0

    for path in CALL_PAGES:
        print(f"\n=== {path} ===")
        result = scrape_call_page(path)
        if not result:
            print("  SKIP: no data")
            failed += 1
            continue

        core, attachments = result
        call_id, n_attrs, n_attach = save_call(core, attachments)
        print(f"  Saved: {core['title'][:60]} | status={core['status']} | attach={n_attach}")
        success += 1

    print(f"\nDONE — {success} saved, {failed} failed")


if __name__ == "__main__":
    main()

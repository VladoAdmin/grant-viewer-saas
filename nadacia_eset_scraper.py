#!/usr/bin/env python3
"""Nadácia ESET scraper — scrapes grant calls from nadaciaeset.sk"""

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
    upsert_grant_calls_v2,
)

URL = "https://www.nadaciaeset.sk/grantove-vyzvy.html"


def parse_date(text):
    if not text:
        return None
    m = re.search(r"(\d{1,2})\.\s*(\w+)\s*(\d{4})", text)
    if m:
        months = {"januára": 1, "februára": 2, "marca": 3, "apríla": 4, "mája": 5, "júna": 6,
                   "júla": 7, "augusta": 8, "septembra": 9, "októbra": 10, "novembra": 11, "decembra": 12}
        d = int(m.group(1))
        mo = months.get(m.group(2).lower())
        y = int(m.group(3))
        if mo:
            return f"{y:04d}-{mo:02d}-{d:02d}"
    return None


def main():
    print("Scraping Nadácia ESET...")
    r = requests.get(URL, timeout=15)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")

    text = soup.get_text(" ", strip=True)

    # Extract key info
    title = "Nadácia ESET: Podpora popularizácie vedy a výskumu 2026"

    # Dates
    announced = parse_date(re.search(r"Zverejnenie výzvy:\s*(.+?)(?:\n|$)", text).group(1)) if re.search(r"Zverejnenie výzvy:\s*(.+?)(?:\n|$)", text) else None
    deadline = parse_date(re.search(r"Uzávierka[^:]*:\s*(.+?)(?:\n|$)", text).group(1)) if re.search(r"Uzávierka[^:]*:\s*(.+?)(?:\n|$)", text) else None

    # Allocation
    alloc = None
    m = re.search(r"vyčlenených?\s*([\d\s]+)\s*EUR", text, re.IGNORECASE)
    if m:
        try:
            alloc = float(m.group(1).replace(" ", "").replace("\xa0", ""))
        except:
            pass

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if deadline and deadline < now:
        status = "Uzavretá"
    elif announced and announced <= now:
        status = "Otvorená"
    else:
        status = "Plánovaná"

    core = {
        "source": "nadaciaeset.sk",
        "source_url": URL,
        "call_url": URL,
        "title": title[:500],
        "announced_at": announced,
        "deadline_at": deadline,
        "provider": "Nadácia ESET",
        "call_type": "Grantová výzva",
        "total_allocation": alloc,
        "eligible_applicants": "občianske združenie; nezisková organizácia; neinvestičný fond; nadácia; škola; obec; rozpočtové a príspevkové organizácie; záujmové združenie právnických osôb; verejná výskumná inštitúcia",
        "status": status,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }

    saved = upsert_grant_calls_v2([core])
    call_id = saved[0]["id"] if saved else None
    if call_id:
        delete_call_attributes(call_id)
        attrs = [
            {"grant_call_id": call_id, "key": "Vyhlasovateľ", "value": core["provider"], "value_type": "text"},
            {"grant_call_id": call_id, "key": "Max. grant", "value": "5 000 EUR", "value_type": "text"},
            {"grant_call_id": call_id, "key": "Spolufinancovanie", "value": "min. 10%", "value_type": "text"},
        ]
        insert_call_attributes(attrs)
        print(f"Saved: {title} | status={status} | alloc={alloc}")
    else:
        print("FAIL: could not save")

    print("DONE — 1 call")


if __name__ == "__main__":
    main()

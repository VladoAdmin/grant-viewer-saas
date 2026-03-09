#!/usr/bin/env python3
"""Scrape calls from fpu.sk (Fond na podporu umenia) and write to grant_calls_v2."""

import os
import re
import sys
import uuid
from datetime import datetime, timezone

from playwright.sync_api import sync_playwright

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from storage import (
    delete_call_attributes,
    delete_call_attachments,
    insert_call_attributes,
    insert_call_attachments,
    upsert_grant_calls_v2,
)

SOURCE = "fpu.sk"
SOURCE_URL = "https://www.fpu.sk/sk/vyzvy/"


def _clean(s):
    return re.sub(r"\s+", " ", (s or "").strip())


def _parse_date(text):
    if not text:
        return None
    m = re.search(r"(\d{1,2})\.(\d{1,2})\.(\d{4})", text)
    if m:
        try:
            return datetime(int(m.group(3)), int(m.group(2)), int(m.group(1))).strftime("%Y-%m-%d")
        except ValueError:
            pass
    return None


def scrape_fpu(limit=5, status_filter=None):
    """Scrape FPU calls from the main page table."""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(SOURCE_URL, wait_until="networkidle", timeout=30000)
        page.wait_for_timeout(3000)

        body = page.inner_text("body")

        # Parse calls via regex from page text
        import re as _re
        pattern = r'Výzva\s+(\d+/\d{4})\s+(\d{2}\.\d{2}\.\d{4}\s*[–-]\s*\d{2}\.\d{2}\.\d{4})\s*\n([\d.,\s]+)\n\s*(OTVORENÁ|ZATVORENÁ|PLÁNOVANÁ)'
        matches = _re.findall(pattern, body)

        call_list = []
        for m in matches:
            call_list.append({
                "code": m[0],
                "dateRange": m[1],
                "programs": m[2].strip().rstrip(","),
                "status": m[3],
            })

        # Get PDF links
        pdf_map = {}
        pdf_links = page.evaluate('''() => {
            const pdfs = {};
            const links = document.querySelectorAll('a[href*="vyzva"][href*=".pdf"]');
            for (const a of links) {
                const href = a.href;
                const m = href.match(/vyzva[_-]?(?:c[_-]?)?0?(\\d)/i);
                if (m) pdfs[m[1]] = href;
            }
            return pdfs;
        }''')

        calls = {"calls": call_list, "pdfs": pdf_links}

        browser.close()

    return calls


def save_call(call_data, pdf_url=None):
    """Save a parsed FPU call to Supabase."""
    now = datetime.now(timezone.utc).isoformat()
    code = call_data["code"]
    status = call_data["status"].upper()

    # Parse dates from range like "08.12.2025 – 12.01.2026"
    dates = re.findall(r"\d{2}\.\d{2}\.\d{4}", call_data.get("dateRange", ""))
    announced = _parse_date(dates[0]) if len(dates) > 0 else None
    deadline = _parse_date(dates[1]) if len(dates) > 1 else None

    status_map = {
        "OTVORENÁ": "Otvorená",
        "ZATVORENÁ": "Uzavretá",
        "PLÁNOVANÁ": "Plánovaná",
    }

    call_url = f"https://www.fpu.sk/sk/vyzvy/#vyzva-{code.replace('/', '-')}"

    core = {
        "source": SOURCE,
        "source_url": SOURCE_URL,
        "call_url": call_url,
        "title": f"FPU Výzva {code}",
        "announced_at": announced,
        "deadline_at": deadline,
        "provider": "Fond na podporu umenia",
        "call_type": None,
        "total_allocation": None,
        "eligible_applicants": None,
        "status": status_map.get(status, status),
        "updated_at": now,
    }

    saved = upsert_grant_calls_v2([core])
    call_id = saved[0]["id"]

    delete_call_attributes(call_id)
    delete_call_attachments(call_id)

    # Attributes
    attrs = [
        {"id": str(uuid.uuid4()), "grant_call_id": call_id, "key": "Kód výzvy", "value": code, "value_type": "text"},
        {"id": str(uuid.uuid4()), "grant_call_id": call_id, "key": "Podporované programy", "value": call_data.get("programs", ""), "value_type": "text"},
        {"id": str(uuid.uuid4()), "grant_call_id": call_id, "key": "Stav", "value": status_map.get(status, status), "value_type": "text"},
    ]
    if call_data.get("dateRange"):
        attrs.append({"id": str(uuid.uuid4()), "grant_call_id": call_id, "key": "Termín predkladania", "value": call_data["dateRange"], "value_type": "text"})

    insert_call_attributes([a for a in attrs if a["value"]])

    # PDF attachment
    if pdf_url:
        insert_call_attachments([{
            "id": str(uuid.uuid4()),
            "grant_call_id": call_id,
            "name": f"Výzva {code} (PDF)",
            "url": pdf_url,
            "file_type": "PDF",
        }])

    return call_id


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument("--status", nargs="*", default=None, help="Filter: otvorena, planovana, zatvorena")
    args = parser.parse_args()

    print("Scraping FPU výzvy...")
    data = scrape_fpu()
    calls = data["calls"]
    pdfs = data["pdfs"]

    print(f"Found {len(calls)} calls, {len(pdfs)} PDF links\n")

    processed = 0
    for call in calls:
        if processed >= args.limit:
            break

        status = call["status"].upper()
        if args.status:
            if not any(s.upper() in status for s in args.status):
                continue

        code = call["code"]
        num = code.split("/")[0]
        pdf_url = pdfs.get(num)

        print(f"=== Výzva {code} ===")
        print(f"  Status: {status} | Dátumy: {call['dateRange']} | Programy: {call['programs'][:60]}")
        print(f"  PDF: {pdf_url or 'N/A'}")

        call_id = save_call(call, pdf_url)
        print(f"  Saved: {call_id}\n")
        processed += 1

    print(f"DONE — {processed} calls")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Scrape calls from envirofond.sk and write to grant_calls_v2 + attributes + attachments."""

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

SOURCE = "envirofond.sk"
SOURCE_URL = "https://envirofond.sk/vyzvy/"


def _clean(s):
    return re.sub(r"\s+", " ", (s or "").strip())


def _parse_date(text):
    if not text:
        return None
    m = re.search(r"(\d{1,2})\.\s*(\d{1,2})\.\s*(\d{4})", text)
    if m:
        try:
            return datetime(int(m.group(3)), int(m.group(2)), int(m.group(1))).strftime("%Y-%m-%d")
        except ValueError:
            pass
    return None


def discover_calls(page):
    """Get list of call URLs from the main vyzvy page."""
    page.goto(SOURCE_URL, wait_until="networkidle", timeout=30000)
    page.wait_for_timeout(3000)

    links = page.evaluate('''() => {
        const seen = new Set();
        const results = [];
        const links = document.querySelectorAll('a[href]');
        for (const a of links) {
            const href = a.href;
            const text = a.innerText.trim();
            // Filter: must be on envirofond.sk, have meaningful text, look like a call page
            if (href.includes('envirofond.sk/') && 
                !href.includes('/vyzvy/#') && 
                !href.includes('/dokumenty') &&
                !href.includes('/kontakt') &&
                !href.includes('.pdf') &&
                !href.includes('.doc') &&
                text.length > 10 &&
                !seen.has(href) &&
                (href.includes('vyzva') || href.includes('specifikac') || href.includes('mof-') || href.includes('2024') || href.includes('2025') || href.includes('2026'))) {
                seen.add(href);
                results.push({href, text: text.substring(0, 150)});
            }
        }
        return results;
    }''')

    return links


def scrape_detail(page, url):
    """Scrape a single call detail page."""
    page.goto(url, wait_until="networkidle", timeout=30000)
    page.wait_for_timeout(2000)

    title = page.title().replace(" - Environmentálny Fond", "").strip()
    body_text = page.inner_text("body")

    # Extract deadline from text
    deadline_raw = None
    deadline = None
    m = re.search(r"[Tt]ermín\s+na\s+podanie\s+žiadosti\s+(?:je\s+)?do\s+(\d{1,2}\.\s*\d{1,2}\.\s*\d{4})", body_text)
    if m:
        deadline_raw = m.group(1)
        deadline = _parse_date(deadline_raw)
    
    if not deadline:
        m = re.search(r"[Uu]závierka[:\s]*(\d{1,2}\.\s*\d{1,2}\.\s*\d{4})", body_text)
        if m:
            deadline_raw = m.group(1)
            deadline = _parse_date(deadline_raw)

    # Get attachments (PDFs, DOCs)
    attachments_raw = page.evaluate('''() => {
        return Array.from(document.querySelectorAll('a[href]')).map(a => ({
            href: a.href,
            text: a.innerText.trim().substring(0, 200)
        })).filter(x => x.text.length > 3 && 
            (x.href.endsWith('.pdf') || x.href.endsWith('.doc') || x.href.endsWith('.docx') || 
             x.href.endsWith('.xls') || x.href.endsWith('.xlsx') || x.href.includes('download')))
    }''')

    # Deduplicate attachments
    seen_urls = set()
    attachments = []
    for a in attachments_raw:
        if a["href"] not in seen_urls:
            seen_urls.add(a["href"])
            ext = a["href"].rsplit(".", 1)[-1].upper() if "." in a["href"] else None
            attachments.append({
                "name": _clean(a["text"])[:200],
                "url": a["href"],
                "file_type": ext if ext in ("PDF", "DOC", "DOCX", "XLS", "XLSX") else None,
            })

    return {
        "title": title,
        "url": url,
        "deadline": deadline,
        "deadline_raw": deadline_raw,
        "body_snippet": body_text[:500],
        "attachments": attachments,
    }


def save_call(detail):
    """Save a scraped call to Supabase."""
    now = datetime.now(timezone.utc).isoformat()

    core = {
        "source": SOURCE,
        "source_url": SOURCE_URL,
        "call_url": detail["url"],
        "title": detail["title"],
        "announced_at": None,
        "deadline_at": detail["deadline"],
        "provider": "Environmentálny fond",
        "call_type": None,
        "total_allocation": None,
        "eligible_applicants": None,
        "status": "Otvorená" if detail["deadline"] and detail["deadline"] >= datetime.now().strftime("%Y-%m-%d") else "Uzavretá",
        "updated_at": now,
    }

    saved = upsert_grant_calls_v2([core])
    call_id = saved[0]["id"]

    delete_call_attributes(call_id)
    delete_call_attachments(call_id)

    # Attributes
    attrs = []
    if detail["deadline_raw"]:
        attrs.append({
            "id": str(uuid.uuid4()),
            "grant_call_id": call_id,
            "key": "Termín podania",
            "value": detail["deadline_raw"],
            "value_type": "text",
        })
    attrs.append({
        "id": str(uuid.uuid4()),
        "grant_call_id": call_id,
        "key": "Poskytovateľ",
        "value": "Environmentálny fond",
        "value_type": "text",
    })

    if attrs:
        insert_call_attributes(attrs)

    # Attachments
    att_records = []
    for a in detail["attachments"]:
        att_records.append({
            "id": str(uuid.uuid4()),
            "grant_call_id": call_id,
            "name": a["name"],
            "url": a["url"],
            "file_type": a["file_type"],
        })

    if att_records:
        insert_call_attachments(att_records)

    return call_id, len(attrs), len(att_records)


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=5)
    args = parser.parse_args()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        print("Discovering calls on envirofond.sk ...")
        call_links = discover_calls(page)
        print(f"Found {len(call_links)} call links\n")

        processed = 0
        for link in call_links:
            if processed >= args.limit:
                break

            print(f"=== {link['text'][:80]} ===")
            print(f"  URL: {link['href']}")

            try:
                detail = scrape_detail(page, link["href"])
                call_id, n_attrs, n_attach = save_call(detail)
                print(f"  Deadline: {detail['deadline_raw'] or 'N/A'}")
                print(f"  Status: {'Otvorená' if detail['deadline'] and detail['deadline'] >= datetime.now().strftime('%Y-%m-%d') else 'Uzavretá/N/A'}")
                print(f"  Saved: call_id={call_id} attrs={n_attrs} attachments={n_attach}\n")
                processed += 1
            except Exception as e:
                print(f"  ERROR: {e}\n")

        browser.close()

    print(f"DONE — processed {processed} calls")


if __name__ == "__main__":
    main()

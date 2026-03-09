#!/usr/bin/env python3
"""Scrape calls from planobnovy.sk and write to grant_calls_v2 + attributes + attachments."""

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

SOURCE = "planobnovy.sk"
SOURCE_URL = "https://www.planobnovy.sk/realizacia/vyzvy/"

STATUS_MAP = {
    "status-otvorena": "Otvorená",
    "status-planovana": "Plánovaná",
    "status-uzavreta": "Uzavretá",
    "status-zrusena": "Zrušená",
    "status-uzavreta-vyhodnotena": "Uzavretá - vyhodnotená",
}


def _parse_date(text):
    """Parse various date formats from planobnovy.sk."""
    if not text:
        return None
    text = text.strip()
    # "31. 12. 2025" or "31.12.2025"
    m = re.match(r"(\d{1,2})\.\s*(\d{1,2})\.\s*(\d{4})", text)
    if m:
        try:
            return datetime(int(m.group(3)), int(m.group(2)), int(m.group(1))).strftime("%Y-%m-%d")
        except ValueError:
            pass
    # "6/2024" -> first of month
    m = re.match(r"(\d{1,2})/(\d{4})", text)
    if m:
        try:
            return datetime(int(m.group(2)), int(m.group(1)), 1).strftime("%Y-%m-%d")
        except ValueError:
            pass
    return None


def _clean(s):
    return re.sub(r"\s+", " ", (s or "").strip())


def scrape_all_pages(page):
    """Scrape all pages and return list of raw call dicts."""
    all_calls = []
    for pg in ["", "page2", "page3", "page4", "page5", "page6", "page7", "page8", "page9", "page10"]:
        url = f"{SOURCE_URL}{pg}"
        page.goto(url, wait_until="networkidle", timeout=30000)
        page.wait_for_timeout(3000)

        # Expand all accordions
        page.evaluate('() => { document.querySelectorAll("details").forEach(d => d.open = true) }')
        page.wait_for_timeout(1000)

        calls = page.evaluate('''() => {
            const results = [];
            const details = document.querySelectorAll('details');
            for (const d of details) {
                const summary = d.querySelector('summary');
                if (!summary) continue;
                const title = summary.innerText.trim();
                const statusCls = summary.className;

                // Parse key-value pairs from the accordion content
                const content = d.innerHTML;
                const textContent = d.innerText;

                // Find all links
                const links = [];
                for (const a of d.querySelectorAll('a[href]')) {
                    links.push({href: a.href, text: a.innerText.trim()});
                }

                results.push({
                    title,
                    statusCls,
                    html: content,
                    text: textContent,
                    links
                });
            }
            return results;
        }''')

        if not calls:
            break
        all_calls.extend(calls)
        print(f"  Page '{pg or '1'}': {len(calls)} calls")

    return all_calls


def parse_call(raw):
    """Parse a raw call dict into structured data."""
    title = _clean(raw["title"])
    text = raw["text"]

    # Determine status
    status = "Neznámy"
    for cls, label in STATUS_MAP.items():
        if cls in raw["statusCls"]:
            status = label
            break

    # Extract fields from text content using patterns
    def _extract(label):
        pattern = rf"{re.escape(label)}\s*\n\s*(.+?)(?:\n|$)"
        m = re.search(pattern, text)
        return _clean(m.group(1)) if m else None

    oblast = _extract("Oblasť")
    komponent = _extract("Komponent")
    reforma = _extract("Názov reformy")
    eligible = _extract("Oprávnení žiadatelia")
    vykonavatelia = _extract("Vykonávatelia / rezorty") or _extract("Vykonávatelia")
    datum_vyhlasenia_raw = _extract("Dátum vyhlásenia výzvy") or _extract("Dátum vyhlásenia")
    datum_ukoncenia_raw = _extract("Dátum ukončenia výzvy") or _extract("Dátum ukončenia")
    viac_info = _extract("Viac informácií")

    announced = _parse_date(datum_vyhlasenia_raw)
    deadline = _parse_date(datum_ukoncenia_raw)

    # Detail link - prefer the "Viac informácií" or first external link
    detail_link = ""
    for link in raw["links"]:
        href = link["href"]
        if "viac" in link["text"].lower() or href.endswith(".pdf"):
            detail_link = href
            break
    if not detail_link and raw["links"]:
        # Pick first non-anchor link
        for link in raw["links"]:
            if not link["href"].endswith("#") and "planobnovy.sk/realizacia/vyzvy" not in link["href"]:
                detail_link = link["href"]
                break

    # Build call URL (unique identifier)
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower())[:80]
    call_url = f"https://www.planobnovy.sk/realizacia/vyzvy/#{slug}"

    return {
        "title": title,
        "status": status,
        "oblast": oblast,
        "komponent": komponent,
        "reforma": reforma,
        "eligible": eligible,
        "vykonavatelia": vykonavatelia,
        "announced": announced,
        "deadline": deadline,
        "deadline_raw": datum_ukoncenia_raw,
        "detail_link": detail_link,
        "call_url": call_url,
        "links": raw["links"],
    }


def save_call(parsed):
    """Save a parsed call to Supabase."""
    now = datetime.now(timezone.utc).isoformat()

    core = {
        "source": SOURCE,
        "source_url": SOURCE_URL,
        "call_url": parsed["call_url"],
        "title": parsed["title"],
        "announced_at": parsed["announced"],
        "deadline_at": parsed["deadline"],
        "provider": parsed["vykonavatelia"],
        "call_type": None,
        "total_allocation": None,
        "eligible_applicants": parsed["eligible"],
        "status": parsed["status"],
        "updated_at": now,
    }

    saved = upsert_grant_calls_v2([core])
    call_id = saved[0]["id"]

    # Delete old attrs/attachments
    delete_call_attributes(call_id)
    delete_call_attachments(call_id)

    # Attributes
    attrs = []
    attr_map = {
        "Oblasť": parsed["oblast"],
        "Komponent": parsed["komponent"],
        "Názov reformy": parsed["reforma"],
        "Oprávnení žiadatelia": parsed["eligible"],
        "Vykonávatelia / rezorty": parsed["vykonavatelia"],
        "Dátum vyhlásenia": parsed["announced"] or "",
        "Dátum ukončenia": parsed["deadline_raw"] or "",
        "Stav": parsed["status"],
    }
    for key, value in attr_map.items():
        if value:
            attrs.append({
                "id": str(uuid.uuid4()),
                "grant_call_id": call_id,
                "key": key,
                "value": value,
                "value_type": "text",
            })

    if attrs:
        insert_call_attributes(attrs)

    # Attachments (links)
    attachments = []
    for link in parsed["links"]:
        href = link["href"]
        if href.endswith("#") or "planobnovy.sk/realizacia/vyzvy" in href:
            continue
        name = link["text"] or href.split("/")[-1]
        file_type = None
        if href.endswith(".pdf"):
            file_type = "PDF"
        elif href.endswith(".xlsx") or href.endswith(".xls"):
            file_type = "Excel"
        elif href.endswith(".docx") or href.endswith(".doc"):
            file_type = "Word"
        attachments.append({
            "id": str(uuid.uuid4()),
            "grant_call_id": call_id,
            "name": _clean(name)[:200],
            "url": href,
            "file_type": file_type,
        })

    if attachments:
        insert_call_attachments(attachments)

    return call_id, len(attrs), len(attachments)


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=5, help="Max calls to scrape")
    parser.add_argument("--status", nargs="*", default=["otvorena", "planovana"],
                        help="Status classes to include (default: otvorena planovana)")
    parser.add_argument("--all-statuses", action="store_true", help="Include all statuses")
    args = parser.parse_args()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        print(f"Scraping planobnovy.sk ...")
        raw_calls = scrape_all_pages(page)
        browser.close()

    print(f"\nTotal raw calls: {len(raw_calls)}")

    # Parse all
    parsed = [parse_call(r) for r in raw_calls]

    # Filter by status
    if not args.all_statuses:
        import unicodedata
        def _norm(s):
            return unicodedata.normalize("NFD", s.lower()).encode("ascii", "ignore").decode()
        status_filter = {_norm(s) for s in args.status}
        parsed = [c for c in parsed if any(s in _norm(c["status"]) for s in status_filter)]
        print(f"After status filter: {len(parsed)}")

    # Limit
    parsed = parsed[:args.limit]
    print(f"Processing {len(parsed)} calls\n")

    for c in parsed:
        print(f"=== {c['title'][:80]} ===")
        print(f"  Status: {c['status']} | Vyhlásená: {c['announced']} | Ukončenie: {c['deadline_raw']}")
        call_id, n_attrs, n_attach = save_call(c)
        print(f"  Saved: call_id={call_id} attrs={n_attrs} attachments={n_attach}\n")

    print("DONE")


if __name__ == "__main__":
    main()

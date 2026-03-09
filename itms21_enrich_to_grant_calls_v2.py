#!/usr/bin/env python3
"""Enrich selected ITMS21 calls and write results into the existing viewer tables.

Targets existing tables used by grant-viewer:
- grant_calls_v2 (core)
- grant_call_attributes (EAV)
- grant_call_attachments (attachments)

Approach:
- Fetch detail pages with Playwright (ITMS21 is JS/Next).
- Deterministically parse key fields (esp. "Oprávnení žiadatelia") from HTML.
- Optionally use cloud LLM via v2.llm_client (OpenRouter/OpenAI/etc.) for extra fields.

Usage:
  source venv/bin/activate
  export SUPABASE_URL=... SUPABASE_KEY=...
  python3 v2/itms21_enrich_to_grant_calls_v2.py --ids 3751 3749 3747 --llm-provider openrouter
"""

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from typing import Optional, Tuple

from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

# Ensure project root on path (so we can import storage.py)
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from storage import (
    delete_call_attributes,
    delete_call_attachments,
    insert_call_attributes,
    insert_call_attachments,
    upsert_grant_calls_v2,
)


def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip())


def _parse_money_eur(text: str) -> Optional[float]:
    if not text:
        return None
    t = text
    t = t.replace("\u00a0", " ")
    t = t.replace("€", "")
    t = t.replace("Eur", "")
    t = t.replace("EUR", "")
    t = t.strip()
    # keep digits, space, comma, dot
    t = re.sub(r"[^0-9,\. ]+", "", t)
    # remove spaces thousands
    t = t.replace(" ", "")
    # Slovak uses comma decimal
    if t.count(",") == 1 and t.count(".") == 0:
        t = t.replace(",", ".")
    try:
        return float(t)
    except Exception:
        return None


def _parse_date_sk(text: str) -> Optional[str]:
    """Parse '12. 1. 2026' -> '2026-01-12'. Returns ISO or None."""
    if not text:
        return None
    m = re.search(r"(\d{1,2})\.\s*(\d{1,2})\.\s*(\d{4})", text)
    if not m:
        return None
    d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
    return f"{y:04d}-{mo:02d}-{d:02d}"


def fetch_html_and_attachments(url: str):
    """Fetch HTML and extract all document links from section "Doplňujúce informácie a dokumenty".

    We do NOT download files.
    - For "URL adresy" we parse <a href> links from HTML.
    - For "Súbory na stiahnutie" (JS buttons without href) we click the Download buttons in Playwright
      and capture the resolved download URL + suggested filename.

    This is intended for small batches (e.g., 5 calls) during setup.
    """
    attachments: list[dict] = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            page = browser.new_page(viewport={"width": 1280, "height": 720})
            page.goto(url, wait_until="networkidle", timeout=45000)
            page.wait_for_timeout(1500)

            # Expand accordion section "Doplňujúce informácie a dokumenty" (needed to make buttons visible)
            try:
                acc_btn = page.locator('button:has-text("Doplňujúce informácie a dokumenty")')
                if acc_btn.count():
                    acc_btn.first.click(timeout=2000)
                    page.wait_for_timeout(300)
            except Exception:
                pass

            html = page.content()

            # 1) URL adresy: extract hrefs from HTML (fast)
            try:
                soup = BeautifulSoup(html, "html.parser")
                # Find dt "URL adresy" and grab following dd
                for dt in soup.find_all('dt'):
                    if _clean(dt.get_text(' ', strip=True)).lower().startswith('url adresy'):
                        dd = dt.find_next_sibling('dd')
                        if dd:
                            for a in dd.find_all('a', href=True):
                                href = a['href']
                                name = _clean(a.get_text(' ', strip=True)) or href
                                attachments.append({
                                    'name': name[:500],
                                    'url': href,
                                    'file_type': 'link',
                                })
                        break
            except Exception:
                pass

            # 2) Súbory na stiahnutie: click "Stiahnuť" buttons and capture API URL (no file download)
            try:
                dd = page.locator('dt:has-text("Súbory na stiahnutie")').locator('xpath=following-sibling::dd[1]')
                rows = dd.locator('li')
                cap = min(rows.count(), 5)

                for i in range(cap):
                    row = rows.nth(i)
                    # filename is text of li (without button label ideally)
                    filename = row.inner_text(timeout=2000)
                    filename = _clean(filename.replace('Stiahnuť', ''))

                    btn = row.locator('button:has-text("Stiahnuť")')
                    if btn.count() == 0:
                        continue

                    captured = []

                    def on_response(resp):
                        try:
                            u = resp.url
                            ct = (resp.headers or {}).get('content-type', '')
                            if 'api.itms21.sk/public/v1/dokument/' in u and ('octet-stream' in ct or 'application/' in ct):
                                captured.append(u)
                        except Exception:
                            pass

                    page.on('response', on_response)
                    try:
                        btn.first.click(timeout=5000)
                        page.wait_for_timeout(1200)
                    except Exception:
                        pass
                    try:
                        page.remove_listener('response', on_response)
                    except Exception:
                        pass

                    if captured:
                        u = captured[-1]
                        ft = filename.split('.')[-1].lower() if '.' in filename else None
                        attachments.append({
                            'name': (filename or 'dokument')[:500],
                            'url': u,
                            'file_type': ft,
                        })
            except Exception:
                pass

            # de-dup by url
            seen = set()
            dedup = []
            for a in attachments:
                u = a.get('url')
                if not u or u in seen:
                    continue
                seen.add(u)
                dedup.append(a)

            return html, dedup
        finally:
            browser.close()


def extract_dt_dd(html: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    out = {}
    for dl in soup.find_all("dl"):
        dts = dl.find_all("dt")
        for dt in dts:
            dd = dt.find_next_sibling("dd")
            if not dd:
                continue
            key = _clean(dt.get_text(" ", strip=True)).rstrip(":")
            val = _clean(dd.get_text(" ", strip=True))
            if key and val:
                # keep first occurrence
                out.setdefault(key, val)
    return out


def extract_core_fields(dtdd: dict) -> dict:
    """Extract key ITMS21 fields from dt/dd mapping."""
    # Primary labels observed on ITMS21 detail page
    return {
        'Program': dtdd.get('Program'),
        'Vyhlasovateľ výzvy': dtdd.get('Vyhlasovateľ výzvy') or dtdd.get('Vyhlasovateľ výzvy'),
        'Druh výzvy': dtdd.get('Druh výzvy'),
        'Typ výzvy': dtdd.get('Typ výzvy'),
        'Predvýber na základe projektového zámeru': dtdd.get('Predvýber na základe projektového zámeru'),
        'Kód výzvy': dtdd.get('Kód výzvy'),
        'Dátum vyhlásenia': dtdd.get('Dátum vyhlásenia'),
        'Dátum ukončenia': dtdd.get('Dátum ukončenia') or dtdd.get('Dátum uzavretia'),
        'Vyčlenené finančné prostriedky za zdroj EÚ': dtdd.get('Vyčlenené finančné prostriedky za zdroj EÚ') or dtdd.get('Finančné prostriedky vyčlenené na výzvu za zdroj EÚ'),
        'Oprávnený žiadateľ': dtdd.get('Oprávnený žiadateľ') or dtdd.get('Oprávnení žiadatelia'),
        'Miesto realizácie': dtdd.get('Miesto realizácie'),
        'Posudzované obdobia': dtdd.get('Posudzované obdobia'),
    }


def extract_eligible_applicants(html: str) -> Tuple[Optional[str], list[str]]:
    soup = BeautifulSoup(html, "html.parser")

    # 1) Prefer section "Oprávnení žiadatelia" in details/accordion
    # Look for summary/span text
    elig_list = []
    elig_text = None

    # a) <summary>Oprávnení žiadatelia</summary> then list items
    for summary in soup.find_all(["summary", "button", "h2", "h3", "span"]):
        t = _clean(summary.get_text(" ", strip=True))
        if t.lower() == "oprávnení žiadatelia" or "oprávnení žiadatelia" in t.lower():
            container = summary.find_parent()
            if container:
                lis = container.find_all("li")
                vals = [_clean(li.get_text(" ", strip=True)) for li in lis]
                vals = [v for v in vals if v]
                if vals:
                    elig_list = vals
                    elig_text = "; ".join(vals)
                    return elig_text, elig_list

    # b) dt/dd pair "Oprávnený žiadateľ" (singular) or "Oprávnení žiadatelia"
    dtdd = extract_dt_dd(html)
    for k in ["Oprávnení žiadatelia", "Oprávnený žiadateľ", "Oprávnení žiadatelia:"]:
        if k in dtdd:
            elig_text = dtdd[k]
            # attempt split by comma
            parts = [p.strip() for p in re.split(r"[,;]", elig_text) if p.strip()]
            elig_list = parts or [elig_text]
            return elig_text, elig_list

    return None, []


def _find_allocation_text(dtdd: dict, html: str) -> Optional[str]:
    # 1) Try dt/dd mapping with fuzzy key match
    for k, v in dtdd.items():
        kk = _clean(k).lower()
        if 'zdroj eú' in kk and ('vyčlenen' in kk or 'vyclenen' in kk or 'finančné prostriedky' in kk or 'financne prostriedky' in kk):
            if v:
                return v

    # 2) Try regex directly from visible text
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text(" ", strip=True).replace("\u00a0", " ")
    m = re.search(r"Vyčlenené\s+finančné\s+prostriedky\s+za\s+zdroj\s*EÚ\s*:?\s*([0-9][0-9\s\.,]+)\s*€", text, re.IGNORECASE)
    if m:
        return m.group(1) + " €"

    # Alternate label variant (split dt)
    m = re.search(r"Finančné\s+prostriedky\s+vyčlenené\s+na\s+výzvu\s+za\s+zdroj\s*EÚ\s*:?\s*([0-9][0-9\s\.,]+)\s*€", text, re.IGNORECASE)
    if m:
        return m.group(1) + " €"

    return None


def build_core_record(url: str, html: str) -> tuple[dict, dict]:
    soup = BeautifulSoup(html, "html.parser")
    title = None
    h1 = soup.find("h1")
    if h1:
        title = _clean(h1.get_text(" ", strip=True))

    dtdd = extract_dt_dd(html)
    fields = extract_core_fields(dtdd)

    announced = _parse_date_sk(fields.get('Dátum vyhlásenia'))
    deadline = _parse_date_sk(fields.get('Dátum ukončenia'))

    provider = fields.get('Vyhlasovateľ výzvy')

    alloc_txt = _find_allocation_text(dtdd, html)
    total_allocation = _parse_money_eur(alloc_txt) if alloc_txt else None

    elig_text, elig_list = extract_eligible_applicants(html)
    # If the plural list exists, prefer it
    if elig_list:
        elig_text = '; '.join(elig_list)

    # IMPORTANT: show Typ výzvy in UI under call.status (DetailModal label will be fixed)
    status = fields.get('Typ výzvy')

    core = {
        "source": "portal.itms21.sk",
        "source_url": "https://portal.itms21.sk/vyhlasene-vyzvy/",
        "call_url": url,
        "title": (title or url)[:500],
        "announced_at": announced,
        "deadline_at": deadline,
        "provider": (provider or "")[:500] or None,
        "call_type": fields.get('Druh výzvy') or None,
        "total_allocation": total_allocation,
        "eligible_applicants": (elig_text or "")[:2000] or None,
        "status": (status or '')[:200] or None,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }

    # Extended attrs to display in viewer
    extended = {
        'Program': fields.get('Program'),
        'Vyhlasovateľ výzvy': provider,
        'Druh výzvy': fields.get('Druh výzvy'),
        'Typ výzvy': fields.get('Typ výzvy'),
        'Predvýber na základe projektového zámeru': fields.get('Predvýber na základe projektového zámeru'),
        'Kód výzvy': fields.get('Kód výzvy'),
        'Miesto realizácie': fields.get('Miesto realizácie'),
        'Posudzované obdobia': fields.get('Posudzované obdobia'),
        'Oprávnený žiadateľ': fields.get('Oprávnený žiadateľ'),
    }

    return core, extended


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ids", nargs="+", required=True, help="ITMS21 call ids, e.g. 3751")
    args = ap.parse_args()

    for cid in args.ids:
        url = f"https://portal.itms21.sk/vyhlasena-vyzva/?id={cid}"
        print(f"\n=== ITMS21 enrich {cid} ===")
        html, found_attachments = fetch_html_and_attachments(url)
        core, extended = build_core_record(url, html)

        # Upsert core
        saved = upsert_grant_calls_v2([core])
        call_id = saved[0]["id"] if saved else None
        print(f"saved call_id={call_id} title={core['title'][:80]}")

        # Attributes / attachments
        if call_id:
            delete_call_attributes(call_id)
            delete_call_attachments(call_id)

            attrs = []

            # Extended, human-readable keys for viewer
            for k, v in (extended or {}).items():
                if v:
                    attrs.append({
                        "grant_call_id": call_id,
                        "key": k,
                        "value": str(v)[:10000],
                        "value_type": "text",
                    })

            # Also store normalized keys for downstream processing
            elig = core.get("eligible_applicants")
            if elig:
                attrs.append({
                    "grant_call_id": call_id,
                    "key": "opravneni_ziadatelia",
                    "value": elig,
                    "value_type": "text",
                })
            if core.get("provider"):
                attrs.append({
                    "grant_call_id": call_id,
                    "key": "vyhlasovatel_vyzvy",
                    "value": core["provider"],
                    "value_type": "text",
                })
            if core.get("total_allocation") is not None:
                attrs.append({
                    "grant_call_id": call_id,
                    "key": "alokacia_eu",
                    "value": str(core["total_allocation"]),
                    "value_type": "number",
                })

            if attrs:
                insert_call_attributes(attrs)

            # Attachments (downloads)
            att_payload = []
            for a in (found_attachments or []):
                if a.get('url'):
                    att_payload.append({
                        'grant_call_id': call_id,
                        'name': (a.get('name') or '')[:500],
                        'url': a.get('url'),
                        'file_type': a.get('file_type'),
                    })
            if att_payload:
                insert_call_attachments(att_payload)

            print(f"inserted attrs={len(attrs)} attachments={len(att_payload)}")

    print("\nDONE")


if __name__ == "__main__":
    main()

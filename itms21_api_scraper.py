#!/usr/bin/env python3
"""ITMS21 scraper using the public REST API (no Playwright needed).

API base: https://api.itms21.sk/public/v1
Endpoints:
  GET /vyzva/?limit=200&offset=0  - list all calls
  GET /vyzva/id/{id}              - call detail

Usage:
  source venv/bin/activate
  python3 v2/itms21_api_scraper.py --limit 200
  python3 v2/itms21_api_scraper.py --ids 3742 3751
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone

import requests

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from storage import (
    delete_call_attributes,
    delete_call_attachments,
    insert_call_attributes,
    insert_call_attachments,
    upsert_grant_calls_v2,
)

API_BASE = "https://api.itms21.sk/public/v1"
HEADERS = {
    "Accept": "application/json",
    "Origin": "https://portal.itms21.sk",
    "Referer": "https://portal.itms21.sk/",
}


def api_get(path, params=None):
    url = f"{API_BASE}{path}"
    r = requests.get(url, headers=HEADERS, params=params, timeout=30)
    r.raise_for_status()
    return r.json()


def list_all_calls(limit=200):
    """Get all call IDs from the API."""
    data = api_get("/vyzva/", params={"limit": limit, "offset": 0})
    return data.get("results", [])


def get_call_detail(call_id):
    """Get full detail for a single call."""
    return api_get(f"/vyzva/id/{call_id}")


def ts_to_date(ts):
    """Convert millisecond timestamp to ISO date string."""
    if not ts:
        return None
    try:
        dt = datetime.fromtimestamp(ts / 1000, tz=timezone.utc)
        return dt.strftime("%Y-%m-%d")
    except Exception:
        return None


def process_call(detail):
    """Convert API detail into core record + attributes + attachments."""
    call_id_itms = detail.get("id")
    url = f"https://portal.itms21.sk/vyhlasena-vyzva/?id={call_id_itms}"

    title = detail.get("nazovSk") or detail.get("nazovEn") or f"ITMS21 #{call_id_itms}"
    kod = detail.get("kod", "")

    # Dates
    announced = ts_to_date(detail.get("datumVyhlasenia"))
    deadline = ts_to_date(detail.get("datumUzavretia"))

    # Provider (vyhlasovatel)
    vyhlasovatel = detail.get("vyhlasovatel", {})
    provider = vyhlasovatel.get("nazovSk") if isinstance(vyhlasovatel, dict) else None

    # Program
    program = detail.get("program", {})
    program_name = program.get("nazovSk") if isinstance(program, dict) else None

    # Allocation (EU source)
    alloc_eu = detail.get("sumaEu")
    alloc_sr = detail.get("sumaSr")
    alloc_total = detail.get("sumaSpolu")

    # Type
    druh = detail.get("druhVyzvy", {})
    druh_name = druh.get("nazovSk") if isinstance(druh, dict) else None

    typ = detail.get("typVyzvy", {})
    typ_name = typ.get("nazovSk") if isinstance(typ, dict) else None

    # Status
    stav = detail.get("stavVyzvy", {})
    status = stav.get("nazovSk") if isinstance(stav, dict) else None

    # Eligible applicants
    opravneni = detail.get("opravneniZiadatelia", [])
    if isinstance(opravneni, list):
        elig_parts = []
        for oz in opravneni:
            if isinstance(oz, dict):
                elig_parts.append(oz.get("nazovSk") or oz.get("nazov") or str(oz))
            else:
                elig_parts.append(str(oz))
        elig_text = "; ".join(elig_parts) if elig_parts else None
    else:
        elig_text = str(opravneni) if opravneni else None

    # Location
    miesto = detail.get("miestoRealizacie", [])
    if isinstance(miesto, list):
        loc_parts = [m.get("nazovSk", str(m)) if isinstance(m, dict) else str(m) for m in miesto]
        location = "; ".join(loc_parts) if loc_parts else None
    else:
        location = str(miesto) if miesto else None

    core = {
        "source": "portal.itms21.sk",
        "source_url": "https://portal.itms21.sk/vyhlasene-vyzvy/",
        "call_url": url,
        "title": title[:500],
        "announced_at": announced,
        "deadline_at": deadline,
        "provider": (provider or "")[:500] or None,
        "call_type": druh_name,
        "total_allocation": alloc_eu,
        "eligible_applicants": (elig_text or "")[:2000] or None,
        "status": (status or typ_name or "")[:200] or None,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }

    # Extended attributes
    extended = {}
    if program_name:
        extended["Program"] = program_name
    if provider:
        extended["Vyhlasovateľ výzvy"] = provider
    if druh_name:
        extended["Druh výzvy"] = druh_name
    if typ_name:
        extended["Typ výzvy"] = typ_name
    if kod:
        extended["Kód výzvy"] = kod
    if location:
        extended["Miesto realizácie"] = location
    if alloc_eu is not None:
        extended["Alokácia EÚ"] = f"{alloc_eu:,.2f} €"
    if alloc_sr is not None:
        extended["Alokácia ŠR"] = f"{alloc_sr:,.2f} €"
    if alloc_total is not None:
        extended["Alokácia spolu"] = f"{alloc_total:,.2f} €"

    # Specific objectives
    spec_ciele = detail.get("specifickyCielProgramu", [])
    if spec_ciele and isinstance(spec_ciele, list):
        ciele_text = "; ".join(
            sc.get("nazovSk", "") for sc in spec_ciele if isinstance(sc, dict)
        )
        if ciele_text:
            extended["Špecifický cieľ"] = ciele_text[:5000]

    # Attachments (documents)
    dokumenty = detail.get("dokumenty", [])
    attachments = []
    if isinstance(dokumenty, list):
        for doc in dokumenty:
            if isinstance(doc, dict):
                doc_id = doc.get("id")
                doc_name = doc.get("nazov") or doc.get("nazovSk") or f"dokument_{doc_id}"
                doc_url = f"{API_BASE}/dokument/id/{doc_id}" if doc_id else None
                if doc_url:
                    ft = doc_name.rsplit(".", 1)[-1].lower() if "." in doc_name else None
                    attachments.append({
                        "name": doc_name[:500],
                        "url": doc_url,
                        "file_type": ft,
                    })

    return core, extended, attachments


def save_call(core, extended, attachments_raw):
    saved = upsert_grant_calls_v2([core])
    call_id = saved[0]["id"] if saved else None
    if not call_id:
        return None, 0, 0

    delete_call_attributes(call_id)
    delete_call_attachments(call_id)

    attrs = []
    for k, v in extended.items():
        if v:
            attrs.append({
                "grant_call_id": call_id,
                "key": k,
                "value": str(v)[:10000],
                "value_type": "text",
            })

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
    ap = argparse.ArgumentParser()
    ap.add_argument("--ids", nargs="+", type=int, help="Specific ITMS21 call IDs")
    ap.add_argument("--limit", type=int, default=200, help="Max calls to fetch from listing")
    ap.add_argument("--skip-existing", action="store_true", help="Skip IDs already in the listing")
    args = ap.parse_args()

    if args.ids:
        call_ids = args.ids
    else:
        print(f"Fetching call listing (limit={args.limit})...")
        listing = list_all_calls(args.limit)
        call_ids = [item["id"] for item in listing]
        print(f"Found {len(call_ids)} calls in listing")

    success = 0
    failed = 0
    for i, cid in enumerate(call_ids):
        try:
            print(f"\n[{i+1}/{len(call_ids)}] Fetching detail for ID {cid}...")
            detail = get_call_detail(cid)
            core, extended, attachments = process_call(detail)
            call_id, n_attrs, n_attach = save_call(core, extended, attachments)
            print(f"  Saved: call_id={call_id} title={core['title'][:70]} attrs={n_attrs} attach={n_attach}")
            success += 1
            time.sleep(0.3)  # Be nice to the API
        except Exception as e:
            print(f"  FAILED: {e}")
            failed += 1

    print(f"\nDONE — {success} saved, {failed} failed out of {len(call_ids)}")


if __name__ == "__main__":
    main()

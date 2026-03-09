"""ITMS21 handler — scrapes grant calls from the ITMS21 public REST API.

Reuses logic from the existing itms21_api_scraper.py.
API: https://api.itms21.sk/public/v1
"""

import logging
import time
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

import requests

from ..config import ITMS21_API_BASE, REQUEST_DELAY, REQUEST_TIMEOUT
from .base import Attachment, BaseHandler, GrantCall

log = logging.getLogger(__name__)

HEADERS = {
    "Accept": "application/json",
    "Origin": "https://portal.itms21.sk",
    "Referer": "https://portal.itms21.sk/",
}


def _api_get(path: str, params: Optional[Dict] = None) -> Dict:
    """GET request to ITMS21 API."""
    url = f"{ITMS21_API_BASE}{path}"
    r = requests.get(url, headers=HEADERS, params=params, timeout=REQUEST_TIMEOUT)
    r.raise_for_status()
    return r.json()


def _ts_to_date(ts) -> Optional[str]:
    """Convert millisecond timestamp to ISO date string."""
    if ts is None:
        return None
    try:
        dt = datetime.fromtimestamp(ts / 1000, tz=timezone.utc)
        return dt.strftime("%Y-%m-%d")
    except Exception:
        return None


class ITMS21Handler(BaseHandler):
    """Handler for ITMS21 grant calls via public REST API."""

    @property
    def source_name(self) -> str:
        return "portal.itms21.sk"

    @property
    def base_url(self) -> str:
        return "https://portal.itms21.sk/vyhlasene-vyzvy/"

    def get_call_listings(self, limit: int = 200) -> List[Dict]:
        """Get all call IDs from the ITMS21 API."""
        data = _api_get("/vyzva/", params={"limit": limit, "offset": 0})
        results = data.get("results", [])
        log.info(f"[ITMS21] API returned {len(results)} calls")
        return results

    def parse_call_detail(self, listing: Dict) -> Tuple[GrantCall, Dict[str, str], List[Attachment]]:
        """Fetch and parse full detail for a single ITMS21 call."""
        itms_id = listing.get("id")
        detail = _api_get(f"/vyzva/id/{itms_id}")
        time.sleep(REQUEST_DELAY)

        call_url = f"https://portal.itms21.sk/vyhlasena-vyzva/?id={itms_id}"
        title = detail.get("nazovSk") or detail.get("nazovEn") or f"ITMS21 #{itms_id}"
        kod = detail.get("kod", "")

        # Dates
        announced = _ts_to_date(detail.get("datumVyhlasenia"))
        deadline = _ts_to_date(detail.get("datumUzavretia"))

        # Provider
        vyhlasovatel = detail.get("vyhlasovatel", {})
        provider = vyhlasovatel.get("nazovSk") if isinstance(vyhlasovatel, dict) else None

        # Program
        program = detail.get("program", {})
        program_name = program.get("nazovSk") if isinstance(program, dict) else None

        # Allocation
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
        elig_text = None
        if isinstance(opravneni, list):
            parts = []
            for oz in opravneni:
                if isinstance(oz, dict):
                    parts.append(oz.get("nazovSk") or oz.get("nazov") or str(oz))
                else:
                    parts.append(str(oz))
            elig_text = "; ".join(parts) if parts else None

        # Location
        miesto = detail.get("miestoRealizacie", [])
        location = None
        if isinstance(miesto, list):
            loc_parts = [m.get("nazovSk", str(m)) if isinstance(m, dict) else str(m) for m in miesto]
            location = "; ".join(loc_parts) if loc_parts else None

        # Build GrantCall
        call = GrantCall(
            source=self.source_name,
            source_url=self.base_url,
            call_url=call_url,
            title=title[:500],
            announced_at=announced,
            deadline_at=deadline,
            provider=(provider or "")[:500] or None,
            call_type=druh_name,
            total_allocation=str(alloc_eu) if alloc_eu is not None else None,
            status=(status or typ_name or "")[:200] or None,
            eligible_applicants=(elig_text or "")[:2000] or None,
        )

        # Extended attributes
        attributes: Dict[str, str] = {}
        if program_name:
            attributes["Program"] = program_name
        if provider:
            attributes["Vyhlasovateľ výzvy"] = provider
        if druh_name:
            attributes["Druh výzvy"] = druh_name
        if typ_name:
            attributes["Typ výzvy"] = typ_name
        if kod:
            attributes["Kód výzvy"] = kod
        if location:
            attributes["Miesto realizácie"] = location
        if alloc_eu is not None:
            attributes["Alokácia EÚ"] = f"{alloc_eu:,.2f} €"
        if alloc_sr is not None:
            attributes["Alokácia ŠR"] = f"{alloc_sr:,.2f} €"
        if alloc_total is not None:
            attributes["Alokácia spolu"] = f"{alloc_total:,.2f} €"

        # Specific objectives
        spec_ciele = detail.get("specifickyCielProgramu", [])
        if isinstance(spec_ciele, list) and spec_ciele:
            ciele = "; ".join(sc.get("nazovSk", "") for sc in spec_ciele if isinstance(sc, dict))
            if ciele:
                attributes["Špecifický cieľ"] = ciele[:5000]

        # Attachments (documents)
        dokumenty = detail.get("dokumenty", [])
        attachments: List[Attachment] = []
        if isinstance(dokumenty, list):
            for doc in dokumenty:
                if isinstance(doc, dict):
                    doc_id = doc.get("id")
                    doc_name = doc.get("nazov") or doc.get("nazovSk") or f"dokument_{doc_id}"
                    doc_url = f"{ITMS21_API_BASE}/dokument/id/{doc_id}" if doc_id else None
                    if doc_url:
                        ft = doc_name.rsplit(".", 1)[-1].lower() if "." in doc_name else None
                        attachments.append(Attachment(name=doc_name[:500], url=doc_url, file_type=ft))

        return call, attributes, attachments

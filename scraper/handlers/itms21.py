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

    def _extract_name(self, obj, fallback_str: Optional[str] = None) -> Optional[str]:
        """Extract name from API object (dict with nazovSk/nazov or plain string)."""
        if isinstance(obj, dict):
            return obj.get("nazovSk") or obj.get("nazov") or obj.get("skratka")
        if isinstance(obj, str) and obj:
            return obj
        return fallback_str

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

        # Provider / Vyhlasovateľ (API uses "nazov" not "nazovSk")
        vyhlasovatel = detail.get("vyhlasovatel", {})
        provider = self._extract_name(vyhlasovatel)

        # Program
        program = detail.get("program", {})
        program_name = self._extract_name(program)

        # Allocation
        alloc_eu = detail.get("sumaEu")
        alloc_sr = detail.get("sumaSr")
        alloc_total = detail.get("sumaSpolu")

        # Type — API returns "druh" (string like "VYZVA_21") and "typ" (string like "OTVORENA")
        # Also try "druhVyzvy" / "typVyzvy" (dict format) as fallback
        druh_raw = detail.get("druhVyzvy") or detail.get("druh")
        druh_name = self._extract_name(druh_raw)

        typ_raw = detail.get("typVyzvy") or detail.get("typ")
        typ_name = self._extract_name(typ_raw)

        # Status — try stavVyzvy (dict), then derive from uzavreta/vyhlasena flags
        stav_raw = detail.get("stavVyzvy")
        status = self._extract_name(stav_raw)
        if not status:
            if detail.get("zrusena"):
                status = "Zrušená"
            elif detail.get("uzavreta"):
                status = "Uzavretá"
            elif detail.get("vyhlasena"):
                status = "Vyhlásená"
            elif detail.get("pozastavenePredkladanieZonfp"):
                status = "Pozastavená"

        # Eligible applicants from opravneniZiadatelia
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

        # --- NEW ATTRIBUTES ---

        # Opatrenie
        opatrenie = detail.get("opatrenie", [])
        if isinstance(opatrenie, list) and opatrenie:
            opatrenia = "; ".join(
                self._extract_name(o) or "" for o in opatrenie
            )
            opatrenia = opatrenia.strip("; ")
            if opatrenia:
                attributes["Opatrenie"] = opatrenia[:5000]

        # Fond
        fondy = detail.get("fond", [])
        if isinstance(fondy, list) and fondy:
            fond_names = "; ".join(
                self._extract_name(f) or "" for f in fondy
            )
            fond_names = fond_names.strip("; ")
            if fond_names:
                attributes["Fond"] = fond_names

        # Oprávnení žiadatelia (from "ziadatel" API field, not opravneniZiadatelia)
        ziadatel = detail.get("ziadatel", [])
        if isinstance(ziadatel, list) and ziadatel:
            ziadatel_names = "; ".join(
                self._extract_name(z) or str(z) for z in ziadatel
            )
            if ziadatel_names:
                attributes["Oprávnení žiadatelia"] = ziadatel_names[:5000]

        # Posudzované obdobia
        obdobia = detail.get("posudzovaneObdobie", [])
        if isinstance(obdobia, list) and obdobia:
            obd_texts = []
            for i, obd in enumerate(obdobia, 1):
                if isinstance(obd, dict):
                    datum = _ts_to_date(obd.get("datumUzavierky"))
                    if datum:
                        obd_texts.append(f"{i}. uzávierka: {datum}")
            if obd_texts:
                attributes["Posudzované obdobia"] = "; ".join(obd_texts)

        # Štatistiky
        for stat_key, attr_name in [
            ("pocetPredlozenychZiadosti", "Predložených žiadostí"),
            ("pocetSchvalenychZiadosti", "Schválených žiadostí"),
            ("pocetNeschvalenychZiadosti", "Neschválených žiadostí"),
            ("pocetZiadostiVKonani", "Žiadosti v konaní"),
            ("pocetRealizovanychProjektov", "Realizovaných projektov"),
        ]:
            val = detail.get(stat_key)
            if val is not None:
                attributes[attr_name] = str(val)

        # Kontaktný email
        email = detail.get("kontaktEmail")
        if email:
            attributes["Kontaktný email"] = email

        # Programové obdobie
        prog_obdobie = detail.get("programoveObdobie")
        if prog_obdobie:
            attributes["Programové obdobie"] = str(prog_obdobie)

        # Kategória regiónov
        kat_regionov = detail.get("kategoriaRegionov", [])
        if isinstance(kat_regionov, list) and kat_regionov:
            reg_names = "; ".join(
                self._extract_name(r) or "" for r in kat_regionov
            )
            reg_names = reg_names.strip("; ")
            if reg_names:
                attributes["Kategória regiónov"] = reg_names

        # Oprávnené výdavky
        vydavky = detail.get("opravneneVydavky", [])
        if isinstance(vydavky, list) and vydavky:
            vyd_names = "; ".join(
                self._extract_name(v) or "" for v in vydavky
            )
            vyd_names = vyd_names.strip("; ")
            if vyd_names:
                attributes["Oprávnené výdavky"] = vyd_names[:5000]

        log.debug(f"[ITMS21] Call {itms_id}: {len(attributes)} attributes extracted: {list(attributes.keys())}")

        # Attachments (documents) — API uses "dokument" field with uuid
        dokumenty = detail.get("dokument", []) or detail.get("dokumenty", [])
        attachments: List[Attachment] = []
        if isinstance(dokumenty, list):
            for doc in dokumenty:
                if isinstance(doc, dict):
                    doc_uuid = doc.get("uuid")
                    doc_id = doc.get("id")
                    doc_name = doc.get("nazov") or doc.get("nazovSk") or f"dokument_{doc_id or doc_uuid}"
                    if doc_uuid:
                        doc_url = f"{ITMS21_API_BASE}/dokument/uuid/{doc_uuid}"
                    elif doc_id:
                        doc_url = f"{ITMS21_API_BASE}/dokument/id/{doc_id}"
                    else:
                        doc_url = None
                    if doc_url:
                        ft = doc_name.rsplit(".", 1)[-1].lower() if "." in doc_name else None
                        attachments.append(Attachment(name=doc_name[:500], url=doc_url, file_type=ft))

        return call, attributes, attachments

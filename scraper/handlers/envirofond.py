"""Envirofond handler — scrapes grant calls from envirofond.sk.

Envirofond is a WordPress site with no API. Uses Playwright for JS-rendered
pages and BeautifulSoup for HTML parsing of the structured table.

Two discovery sources:
  1. /aktualne-vyzva-a-specifikacie/ — HTML table with dates, status
  2. /vyzvy/ — link-based discovery (catches calls not in table)

Detail pages scraped with Playwright page.evaluate() for PDF/DOCX links.
"""

import logging
import re
import time
from datetime import datetime, timezone
from typing import Dict, List, Optional, Set, Tuple
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from ..config import REQUEST_DELAY, REQUEST_TIMEOUT
from .base import Attachment, BaseHandler, GrantCall

log = logging.getLogger(__name__)

# Pages to scrape
TABLE_URL = "https://envirofond.sk/aktualne-vyzva-a-specifikacie/"
VYZVY_URL = "https://envirofond.sk/vyzvy/"

# Cookie to bypass consent wall
HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Cookie": "cookie_notice_accepted=true",
}

# Generic PDFs to skip (always present, no grant-specific info)
SKIP_FILENAMES = {
    "pouzivatelsky-manual.pdf",
    "informacie_gdpr_ef.pdf",
}

# URL patterns for call pages
CALL_URL_KEYWORDS = [
    "vyzva", "specifikac", "mof-", "odpady", "havarie", "mimoriadna",
    "uvery", "environmentalna", "2024", "2025", "2026",
]

# Exclusion patterns for non-call pages
EXCLUDE_URL_PATTERNS = [
    "/vyzvy/#", "/dokumenty", "/kontakt", "/specifikacie-archiv",
    "/kategoria/", "/tag/", "/page/",
]


def _parse_date(text: str) -> Optional[str]:
    """Parse date from DD.MM.YYYY format to YYYY-MM-DD."""
    if not text:
        return None
    m = re.search(r"(\d{1,2})\.\s*(\d{1,2})\.\s*(\d{4})", text.strip())
    if m:
        try:
            d = datetime(int(m.group(3)), int(m.group(2)), int(m.group(1)))
            return d.strftime("%Y-%m-%d")
        except ValueError:
            pass
    return None


def _clean(s: str) -> str:
    """Clean whitespace from string."""
    return re.sub(r"\s+", " ", (s or "").strip())


def _should_skip_attachment(url: str) -> bool:
    """Check if attachment URL should be skipped (generic docs)."""
    fname = url.rsplit("/", 1)[-1].lower()
    return fname in SKIP_FILENAMES


def _is_call_url(href: str) -> bool:
    """Check if URL looks like a call detail page."""
    href_lower = href.lower()
    if not href_lower.startswith("https://envirofond.sk/"):
        return False
    for pattern in EXCLUDE_URL_PATTERNS:
        if pattern in href_lower:
            return False
    return any(kw in href_lower for kw in CALL_URL_KEYWORDS)


class EnvirofondHandler(BaseHandler):
    """Handler for Envirofond grant calls via HTML scraping + Playwright."""

    def __init__(self):
        self._browser = None
        self._page = None
        self._playwright = None

    @property
    def source_name(self) -> str:
        return "envirofond.sk"

    @property
    def base_url(self) -> str:
        return "https://envirofond.sk/aktualne-vyzva-a-specifikacie/"

    def _ensure_browser(self):
        """Lazily initialize Playwright browser."""
        if self._page is not None:
            return
        from playwright.sync_api import sync_playwright
        self._playwright = sync_playwright().start()
        self._browser = self._playwright.chromium.launch(headless=True)
        self._page = self._browser.new_page()
        log.info("[envirofond] Playwright browser started")

    def _close_browser(self):
        """Close browser if open."""
        if self._browser:
            self._browser.close()
            self._browser = None
            self._page = None
        if self._playwright:
            self._playwright.stop()
            self._playwright = None

    def get_call_listings(self, limit: int = 200) -> List[Dict]:
        """Discover calls from both table page and /vyzvy/ page.

        Returns list of dicts with keys: url, title, announced_at, deadline_at, status
        """
        seen_urls: Set[str] = set()
        listings: List[Dict] = []

        # Source 1: Structured table at /aktualne-vyzva-a-specifikacie/
        table_listings = self._scrape_table()
        for item in table_listings:
            url = item["url"]
            if url not in seen_urls:
                seen_urls.add(url)
                listings.append(item)

        # Source 2: Link discovery at /vyzvy/
        vyzvy_listings = self._scrape_vyzvy_links()
        for item in vyzvy_listings:
            url = item["url"]
            if url not in seen_urls:
                seen_urls.add(url)
                listings.append(item)

        log.info(f"[envirofond] Discovered {len(listings)} calls "
                 f"(table={len(table_listings)}, vyzvy_extra={len(listings) - len(table_listings)})")

        return listings[:limit]

    def _scrape_table(self) -> List[Dict]:
        """Scrape the structured HTML table from /aktualne-vyzva-a-specifikacie/."""
        try:
            r = requests.get(TABLE_URL, headers=HEADERS, timeout=REQUEST_TIMEOUT)
            r.raise_for_status()
        except Exception as e:
            log.error(f"[envirofond] Failed to fetch table page: {e}")
            return []

        soup = BeautifulSoup(r.text, "html.parser")
        table = soup.find("table")
        if not table:
            log.warning("[envirofond] No table found on page")
            return []

        listings = []
        rows = table.find_all("tr")

        for row in rows[1:]:  # skip header row
            cells = row.find_all("td")
            if len(cells) < 4:
                continue

            # Cell 0: title + link
            link = cells[0].find("a", href=True)
            if not link:
                continue

            url = link["href"].strip()
            title = _clean(link.text)
            if not title or not url:
                continue

            # Ensure absolute URL
            if not url.startswith("http"):
                url = urljoin(TABLE_URL, url)

            # Cell 1: "Od:" date
            announced_at = _parse_date(cells[1].text)

            # Cell 2: "Do:" date
            deadline_at = _parse_date(cells[2].text)

            # Cell 3: "Stav:" — extract just the status word before any extra text
            status_text = _clean(cells[3].text)
            # Extract main status (first word/phrase before dash or link text)
            status_match = re.match(r"^(otvorená|uzavretá|uzatvorená|[^\-–]+)", status_text, re.IGNORECASE)
            status = _clean(status_match.group(1)) if status_match else status_text[:100]

            listings.append({
                "url": url,
                "title": title,
                "announced_at": announced_at,
                "deadline_at": deadline_at,
                "status": status,
            })

        log.info(f"[envirofond] Table: found {len(listings)} rows")
        return listings

    def _scrape_vyzvy_links(self) -> List[Dict]:
        """Discover additional calls from the /vyzvy/ page."""
        try:
            r = requests.get(VYZVY_URL, headers=HEADERS, timeout=REQUEST_TIMEOUT)
            r.raise_for_status()
        except Exception as e:
            log.error(f"[envirofond] Failed to fetch vyzvy page: {e}")
            return []

        soup = BeautifulSoup(r.text, "html.parser")
        listings = []
        seen = set()

        for a in soup.find_all("a", href=True):
            href = a["href"].strip()
            text = _clean(a.text)

            if not text or len(text) < 10:
                continue
            if href in seen:
                continue
            if not _is_call_url(href):
                continue
            # Skip file links
            if any(href.lower().endswith(ext) for ext in [".pdf", ".doc", ".docx", ".xls", ".xlsx"]):
                continue

            seen.add(href)
            listings.append({
                "url": href,
                "title": text[:200],
                "announced_at": None,
                "deadline_at": None,
                "status": None,
            })

        log.info(f"[envirofond] Vyzvy links: found {len(listings)} links")
        return listings

    def parse_call_detail(self, listing: Dict) -> Tuple[GrantCall, Dict[str, str], List[Attachment]]:
        """Scrape detail page for a single call using Playwright.

        Extracts title, deadline (from body text), and PDF/DOCX attachments.
        """
        url = listing["url"]
        title = listing.get("title", "")
        announced_at = listing.get("announced_at")
        deadline_at = listing.get("deadline_at")
        status = listing.get("status")

        self._ensure_browser()

        try:
            self._page.goto(url, wait_until="networkidle", timeout=30000)
            self._page.wait_for_timeout(2000)
        except Exception as e:
            log.warning(f"[envirofond] Page load failed for {url}: {e}")
            # Fall back to basic data from listing
            call = GrantCall(
                source=self.source_name,
                source_url=self.base_url,
                call_url=url,
                title=title[:500],
                announced_at=announced_at,
                deadline_at=deadline_at,
                provider="Environmentálny fond",
                status=status,
            )
            return call, {}, []

        # Get title from page if not from table
        page_title = self._page.title().replace(" - Environmentálny Fond", "").strip()
        if not title or len(title) < 5:
            title = page_title

        # Try to get H1 for better title
        try:
            h1 = self._page.query_selector("h1")
            if h1:
                h1_text = _clean(h1.inner_text())
                if h1_text and len(h1_text) > 5:
                    title = h1_text
        except Exception:
            pass

        # Extract deadline from body text if not from table
        if not deadline_at:
            try:
                body_text = self._page.inner_text("body")
                # Pattern 1: "termín na podanie žiadosti do DD.MM.YYYY"
                m = re.search(
                    r"[Tt]ermín\s+na\s+podanie\s+žiadosti\s+(?:je\s+)?do\s+(\d{1,2}\.\s*\d{1,2}\.\s*\d{4})",
                    body_text,
                )
                if m:
                    deadline_at = _parse_date(m.group(1))
                # Pattern 2: "uzávierka: DD.MM.YYYY"
                if not deadline_at:
                    m = re.search(r"[Uu]závierka[:\s]*(\d{1,2}\.\s*\d{1,2}\.\s*\d{4})", body_text)
                    if m:
                        deadline_at = _parse_date(m.group(1))
            except Exception as e:
                log.debug(f"[envirofond] Body text extraction failed: {e}")

        # Extract attachments using page.evaluate() (more robust for WordPress)
        raw_attachments = self._page.evaluate('''() => {
            return Array.from(document.querySelectorAll('a[href]')).map(a => ({
                href: a.href,
                text: a.innerText.trim().substring(0, 200)
            })).filter(x => x.text.length > 2 &&
                (x.href.endsWith('.pdf') || x.href.endsWith('.doc') ||
                 x.href.endsWith('.docx') || x.href.endsWith('.xls') ||
                 x.href.endsWith('.xlsx')))
        }''')

        # Deduplicate and filter attachments
        seen_urls: Set[str] = set()
        attachments: List[Attachment] = []

        for a in raw_attachments:
            href = a["href"]
            if href in seen_urls:
                continue
            if _should_skip_attachment(href):
                log.debug(f"[envirofond] Skipping generic: {href.rsplit('/', 1)[-1]}")
                continue

            seen_urls.add(href)
            name = _clean(a["text"])[:500] or href.rsplit("/", 1)[-1]
            ext = href.rsplit(".", 1)[-1].lower() if "." in href else None

            attachments.append(Attachment(
                name=name,
                url=href,
                file_type=ext,
            ))

        # Determine status
        if not status:
            if deadline_at:
                today = datetime.now().strftime("%Y-%m-%d")
                status = "otvorená" if deadline_at >= today else "uzavretá"
            else:
                status = "otvorená"

        # Build GrantCall
        call = GrantCall(
            source=self.source_name,
            source_url=self.base_url,
            call_url=url,
            title=title[:500],
            announced_at=announced_at,
            deadline_at=deadline_at,
            provider="Environmentálny fond",
            call_type=None,
            total_allocation=None,
            status=status[:200] if status else None,
        )

        # Build attributes
        attributes: Dict[str, str] = {}
        attributes["Poskytovateľ"] = "Environmentálny fond"
        if deadline_at:
            attributes["Termín podania"] = deadline_at
        if announced_at:
            attributes["Dátum vyhlásenia"] = announced_at
        if status:
            attributes["Stav výzvy"] = status

        log.info(f"[envirofond] Detail: {title[:60]} | "
                 f"deadline={deadline_at} | attachments={len(attachments)}")

        return call, attributes, attachments

    def scrape(self, limit: int = 200):
        """Override scrape to manage Playwright lifecycle."""
        try:
            return super().scrape(limit=limit)
        finally:
            self._close_browser()

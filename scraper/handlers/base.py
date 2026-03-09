"""Abstract base handler for grant source scrapers."""

import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional

from ..config import REQUEST_DELAY
from ..db import get_db

log = logging.getLogger(__name__)


@dataclass
class GrantCall:
    """Represents a scraped grant call."""
    source: str
    source_url: str
    call_url: str
    title: str
    announced_at: Optional[str] = None
    deadline_at: Optional[str] = None
    provider: Optional[str] = None
    call_type: Optional[str] = None
    total_allocation: Optional[str] = None
    status: Optional[str] = None
    eligible_applicants: Optional[str] = None


@dataclass
class Attachment:
    """Represents a downloadable attachment."""
    name: str
    url: str
    file_type: Optional[str] = None


@dataclass
class ScrapeResult:
    """Result of a scrape operation."""
    source: str
    calls_found: int = 0
    calls_new: int = 0
    calls_updated: int = 0
    errors: List[str] = field(default_factory=list)
    duration_seconds: float = 0.0


class BaseHandler(ABC):
    """Abstract base handler for grant source scrapers.

    Subclasses must implement:
      - source_name: str property
      - base_url: str property
      - get_call_listings() -> List[Dict]
      - parse_call_detail(listing) -> (GrantCall, Dict[str,str], List[Attachment])
    """

    @property
    @abstractmethod
    def source_name(self) -> str:
        """Unique source identifier, e.g. 'portal.itms21.sk'."""
        ...

    @property
    @abstractmethod
    def base_url(self) -> str:
        """Base URL of the source."""
        ...

    @abstractmethod
    def get_call_listings(self, limit: int = 200) -> List[Dict]:
        """Get list of all available calls (minimal data for comparison).
        Returns list of dicts with at least 'id' or 'url' for identification.
        """
        ...

    @abstractmethod
    def parse_call_detail(self, listing: Dict) -> tuple:
        """Parse full call detail from listing item.
        Returns: (GrantCall, extended_attributes: Dict[str,str], attachments: List[Attachment])
        """
        ...

    def scrape(self, limit: int = 200) -> ScrapeResult:
        """Main scrape method. Orchestrates the full scrape cycle."""
        db = get_db()
        start = time.time()
        result = ScrapeResult(source=self.source_name)

        # Start tracking run
        run = db.start_scraper_run(self.source_name)
        run_id = run["id"] if run else None

        try:
            # 1. Get listings
            log.info(f"[{self.source_name}] Fetching call listings (limit={limit})...")
            listings = self.get_call_listings(limit)
            result.calls_found = len(listings)
            log.info(f"[{self.source_name}] Found {len(listings)} calls")

            # 2. Get existing calls for comparison
            existing = db.get_grant_calls(source=self.source_name, limit=10000)
            existing_urls = {c["call_url"] for c in existing}

            # 3. Process each call
            for i, listing in enumerate(listings):
                try:
                    call, attributes, attachments = self.parse_call_detail(listing)

                    # Upsert call
                    call_data = {
                        "source": call.source,
                        "source_url": call.source_url,
                        "call_url": call.call_url,
                        "title": call.title[:500],
                        "announced_at": call.announced_at,
                        "deadline_at": call.deadline_at,
                        "provider": (call.provider or "")[:500] or None,
                        "call_type": call.call_type,
                        "total_allocation": call.total_allocation,
                        "status": (call.status or "")[:200] or None,
                        "updated_at": datetime.now(timezone.utc).isoformat(),
                    }

                    saved = db.upsert_grant_call(call_data)
                    if not saved:
                        log.warning(f"[{self.source_name}] Failed to save call: {call.title[:60]}")
                        continue

                    call_id = saved["id"]
                    is_new = call.call_url not in existing_urls

                    if is_new:
                        result.calls_new += 1
                    else:
                        result.calls_updated += 1

                    # Save attachments
                    if attachments:
                        att_dicts = [{"name": a.name, "url": a.url, "file_type": a.file_type}
                                     for a in attachments]
                        db.save_attachments(call_id, att_dicts)

                    # Save attributes
                    if attributes:
                        # Add standard attributes from call
                        if call.eligible_applicants:
                            attributes["opravneni_ziadatelia"] = call.eligible_applicants
                        if call.provider:
                            attributes["vyhlasovatel_vyzvy"] = call.provider
                        if call.total_allocation:
                            attributes["alokacia_eu"] = str(call.total_allocation)
                        db.save_attributes(call_id, attributes)

                    log.info(f"[{self.source_name}] [{i+1}/{len(listings)}] "
                             f"{'NEW' if is_new else 'UPD'}: {call.title[:70]} "
                             f"(attrs={len(attributes)}, attach={len(attachments)})")

                    time.sleep(REQUEST_DELAY)

                except Exception as e:
                    error_msg = f"Failed to process listing {i}: {e}"
                    log.error(f"[{self.source_name}] {error_msg}")
                    result.errors.append(error_msg)
                    db.log_error(
                        source="scraper",
                        component=self.source_name,
                        message=error_msg,
                        severity="error",
                    )

        except Exception as e:
            error_msg = f"Scrape failed: {e}"
            log.error(f"[{self.source_name}] {error_msg}")
            result.errors.append(error_msg)
            if run_id:
                db.finish_scraper_run(run_id, status="error", error_message=error_msg,
                                      calls_found=result.calls_found)

        else:
            if run_id:
                db.finish_scraper_run(
                    run_id,
                    status="success" if not result.errors else "partial",
                    calls_found=result.calls_found,
                    calls_new=result.calls_new,
                    calls_updated=result.calls_updated,
                )

        result.duration_seconds = time.time() - start
        log.info(f"[{self.source_name}] Scrape complete in {result.duration_seconds:.1f}s: "
                 f"found={result.calls_found}, new={result.calls_new}, "
                 f"updated={result.calls_updated}, errors={len(result.errors)}")

        return result

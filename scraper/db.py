"""Supabase database client for the scraper.

All DB operations go through this module. Uses raw REST API (not supabase-py)
for minimal dependencies and full control.
"""

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import requests

from .config import SUPABASE_URL, SUPABASE_KEY

log = logging.getLogger(__name__)


class SupabaseClient:
    """Lightweight Supabase REST API client."""

    def __init__(self):
        if not SUPABASE_URL or not SUPABASE_KEY:
            raise RuntimeError("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set")
        self.base_url = SUPABASE_URL
        self.key = SUPABASE_KEY

    def _headers(self, prefer: str = "return=representation") -> Dict[str, str]:
        return {
            "apikey": self.key,
            "Authorization": f"Bearer {self.key}",
            "Content-Type": "application/json",
            "Prefer": prefer,
        }

    def _get(self, table: str, params: Optional[Dict] = None, timeout: int = 30) -> List[Dict]:
        url = f"{self.base_url}/rest/v1/{table}"
        r = requests.get(url, headers=self._headers(), params=params or {}, timeout=timeout)
        r.raise_for_status()
        return r.json() if r.text else []

    def _post(self, table: str, data: Any, prefer: str = "return=representation", timeout: int = 30) -> List[Dict]:
        url = f"{self.base_url}/rest/v1/{table}"
        r = requests.post(url, headers=self._headers(prefer), json=data, timeout=timeout)
        r.raise_for_status()
        return r.json() if r.text else []

    def _delete(self, table: str, params: Dict, timeout: int = 30):
        url = f"{self.base_url}/rest/v1/{table}"
        r = requests.delete(url, headers=self._headers("return=minimal"), params=params, timeout=timeout)
        r.raise_for_status()

    def _rpc(self, fn_name: str, params: Dict, timeout: int = 60) -> Any:
        url = f"{self.base_url}/rest/v1/rpc/{fn_name}"
        r = requests.post(url, headers=self._headers(), json=params, timeout=timeout)
        r.raise_for_status()
        return r.json() if r.text else None

    # =========================================================================
    # Grant calls
    # =========================================================================

    def upsert_grant_call(self, call_data: Dict) -> Optional[Dict]:
        """Upsert a single grant call. Returns saved record with id."""
        url = f"{self.base_url}/rest/v1/grant_calls_v2"
        headers = self._headers("resolution=merge-duplicates,return=representation")
        params = {"on_conflict": "call_url"}
        r = requests.post(url, headers=headers, params=params, json=[call_data], timeout=30)
        r.raise_for_status()
        result = r.json()
        return result[0] if result else None

    def upsert_grant_calls(self, calls: List[Dict]) -> List[Dict]:
        """Upsert multiple grant calls."""
        if not calls:
            return []
        url = f"{self.base_url}/rest/v1/grant_calls_v2"
        headers = self._headers("resolution=merge-duplicates,return=representation")
        params = {"on_conflict": "call_url"}
        r = requests.post(url, headers=headers, params=params, json=calls, timeout=60)
        r.raise_for_status()
        return r.json() if r.text else []

    def get_grant_calls(self, source: Optional[str] = None, limit: int = 1000, include_deleted: bool = False) -> List[Dict]:
        """Get grant calls, optionally filtered by source."""
        params: Dict[str, str] = {
            "select": "*",
            "order": "created_at.desc",
            "limit": str(limit),
        }
        if source:
            params["source"] = f"eq.{source}"
        if not include_deleted:
            params["deleted_at"] = "is.null"
        return self._get("grant_calls_v2", params)

    def get_grant_call_by_id(self, call_id: int) -> Optional[Dict]:
        """Get a single grant call by ID."""
        result = self._get("grant_calls_v2", {"id": f"eq.{call_id}", "limit": "1"})
        return result[0] if result else None

    # =========================================================================
    # Attachments
    # =========================================================================

    def save_attachments(self, grant_call_id: int, attachments: List[Dict]) -> List[Dict]:
        """Save attachments for a grant call. Deletes existing first (idempotent)."""
        self._delete("grant_call_attachments", {"grant_call_id": f"eq.{grant_call_id}"})
        if not attachments:
            return []
        payload = [
            {
                "grant_call_id": grant_call_id,
                "name": att.get("name", "")[:500],
                "url": att["url"],
                "file_type": att.get("file_type"),
            }
            for att in attachments if att.get("url")
        ]
        if not payload:
            return []
        return self._post("grant_call_attachments", payload)

    def get_attachments(self, grant_call_id: int) -> List[Dict]:
        """Get attachments for a grant call."""
        return self._get("grant_call_attachments", {"grant_call_id": f"eq.{grant_call_id}"})

    # =========================================================================
    # Attributes (key-value extracted data)
    # =========================================================================

    def save_attributes(self, grant_call_id: int, attributes: Dict[str, str]) -> List[Dict]:
        """Save extracted attributes. Deletes existing first (idempotent)."""
        self._delete("grant_call_attributes", {"grant_call_id": f"eq.{grant_call_id}"})
        if not attributes:
            return []
        payload = [
            {
                "grant_call_id": grant_call_id,
                "key": k,
                "value": str(v)[:10000],
                "value_type": "text",
            }
            for k, v in attributes.items() if v
        ]
        if not payload:
            return []
        return self._post("grant_call_attributes", payload)

    def get_attributes(self, grant_call_id: int) -> Dict[str, str]:
        """Get attributes as a dict."""
        rows = self._get("grant_call_attributes", {"grant_call_id": f"eq.{grant_call_id}"})
        return {r["key"]: r["value"] for r in rows}

    # =========================================================================
    # Document classification
    # =========================================================================

    def save_classification(self, grant_call_id: int, filename: str, doc_type: str,
                            confidence: float = 0.0, attachment_id: Optional[int] = None) -> Optional[Dict]:
        """Save document classification."""
        payload = {
            "grant_call_id": grant_call_id,
            "filename": filename,
            "doc_type": doc_type,
            "confidence": confidence,
        }
        if attachment_id:
            payload["attachment_id"] = attachment_id
        result = self._post("doc_classification", [payload])
        return result[0] if result else None

    # =========================================================================
    # Chunks (vector storage)
    # =========================================================================

    def delete_chunks_for_call(self, call_id: int):
        """Delete all chunks for a call (idempotent re-embedding)."""
        self._delete("v2_call_chunks", {"call_id": f"eq.{call_id}"})

    def insert_chunks(self, chunks: List[Dict]):
        """Insert chunks in batches."""
        if not chunks:
            return
        headers = self._headers("return=minimal")
        url = f"{self.base_url}/rest/v1/v2_call_chunks"
        for i in range(0, len(chunks), 20):
            batch = chunks[i:i + 20]
            r = requests.post(url, headers=headers, json=batch, timeout=180)
            if r.status_code >= 400:
                log.error(f"Chunk insert error {r.status_code}: {r.text[:300]}")
                r.raise_for_status()

    def chunk_exists(self, call_id: int, source: str) -> bool:
        """Check if chunks already exist for a call+source combo."""
        result = self._get("v2_call_chunks", {
            "call_id": f"eq.{call_id}",
            "source": f"eq.{source}",
            "select": "id",
            "limit": "1",
        })
        return len(result) > 0

    # =========================================================================
    # Scraper runs (admin tracking)
    # =========================================================================

    def start_scraper_run(self, source: str) -> Optional[Dict]:
        """Record start of a scraper run."""
        result = self._post("scraper_runs", [{"source": source, "status": "running"}])
        return result[0] if result else None

    def finish_scraper_run(self, run_id: int, status: str = "success",
                           calls_found: int = 0, calls_new: int = 0,
                           calls_updated: int = 0, chunks_created: int = 0,
                           error_message: Optional[str] = None):
        """Update scraper run with results."""
        url = f"{self.base_url}/rest/v1/scraper_runs"
        data = {
            "status": status,
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "calls_found": calls_found,
            "calls_new": calls_new,
            "calls_updated": calls_updated,
            "chunks_created": chunks_created,
        }
        if error_message:
            data["error_message"] = error_message[:5000]
        r = requests.patch(url, headers=self._headers("return=minimal"),
                           params={"id": f"eq.{run_id}"}, json=data, timeout=30)
        r.raise_for_status()

    def get_last_scraper_runs(self, limit: int = 10) -> List[Dict]:
        """Get recent scraper runs."""
        return self._get("scraper_runs", {
            "order": "started_at.desc",
            "limit": str(limit),
        })

    # =========================================================================
    # Error logging
    # =========================================================================

    def log_error(self, source: str, component: str, message: str,
                  severity: str = "error", call_id: Optional[int] = None,
                  details: Optional[Dict] = None) -> str:
        """Log an error and return error_id."""
        error_id = f"ERR-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:6]}"
        payload = {
            "error_id": error_id,
            "source": source,
            "component": component,
            "severity": severity,
            "message": message[:5000],
            "details": json.dumps(details or {}),
        }
        if call_id:
            payload["call_id"] = call_id
        try:
            self._post("error_log", [payload], prefer="return=minimal")
        except Exception as e:
            log.error(f"Failed to log error to DB: {e}")
        return error_id

    # =========================================================================
    # Search (hybrid)
    # =========================================================================

    def hybrid_search(self, query_text: str, query_embedding: List[float],
                      match_threshold: float = 0.3, match_count: int = 10,
                      call_id: Optional[int] = None, doc_type: Optional[str] = None) -> List[Dict]:
        """Run hybrid search via RPC."""
        params = {
            "query_text": query_text,
            "query_embedding": json.dumps(query_embedding),
            "match_threshold": match_threshold,
            "match_count": match_count,
        }
        if call_id is not None:
            params["call_id_filter"] = call_id
        if doc_type:
            params["doc_type_filter"] = doc_type
        return self._rpc("hybrid_search_chunks", params) or []

    # =========================================================================
    # Cleanup & Dedup
    # =========================================================================

    def cleanup_old_calls(self, months: int = 12) -> int:
        """Soft-delete calls older than threshold."""
        result = self._rpc("cleanup_old_calls", {"months_threshold": months})
        if result and isinstance(result, list) and result:
            return result[0].get("cleaned_count", 0)
        return 0

    def hard_delete_old_chunks(self, months: int = 3) -> int:
        """Hard-delete chunks for long-soft-deleted calls."""
        result = self._rpc("hard_delete_old_chunks", {"months_after_softdelete": months})
        if result and isinstance(result, list) and result:
            return result[0].get("deleted_chunks", 0)
        return 0

    def find_duplicates(self) -> List[Dict]:
        """Find duplicate calls."""
        return self._rpc("find_duplicate_calls", {}) or []


# Module-level singleton
_client: Optional[SupabaseClient] = None


def get_db() -> SupabaseClient:
    """Get or create the DB client singleton."""
    global _client
    if _client is None:
        _client = SupabaseClient()
    return _client

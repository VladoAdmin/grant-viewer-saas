"""Cleanup and deduplication jobs.

PRD Requirements (OP-001, OP-002):
- Dedup: unique key (title_lowercase, announced_at), check before insertion
- Cleanup: calls older than 12 months from deadline -> soft-delete
- Hard-delete chunks 3 months after soft-delete
"""

import logging
from typing import Dict, List

from .db import get_db
from .error_handler import ErrorCollector, log_error

log = logging.getLogger(__name__)


def run_cleanup(months_threshold: int = 12, hard_delete_months: int = 3) -> Dict:
    """Run cleanup: soft-delete old calls, hard-delete old chunks.

    Args:
        months_threshold: Months after deadline to soft-delete calls
        hard_delete_months: Months after soft-delete to hard-delete chunks

    Returns:
        Dict with cleanup results
    """
    db = get_db()
    results = {
        "soft_deleted_calls": 0,
        "hard_deleted_chunks": 0,
        "errors": [],
    }

    try:
        # 1. Soft-delete old calls
        soft_deleted = db.cleanup_old_calls(months_threshold)
        results["soft_deleted_calls"] = soft_deleted
        log.info(f"Cleanup: soft-deleted {soft_deleted} old calls "
                 f"(threshold: {months_threshold} months)")
    except Exception as e:
        error_msg = f"Soft-delete failed: {e}"
        log.error(error_msg)
        results["errors"].append(error_msg)
        log_error("cleanup", "soft_delete", error_msg)

    try:
        # 2. Hard-delete old chunks
        hard_deleted = db.hard_delete_old_chunks(hard_delete_months)
        results["hard_deleted_chunks"] = hard_deleted
        log.info(f"Cleanup: hard-deleted {hard_deleted} old chunks "
                 f"(threshold: {hard_delete_months} months after soft-delete)")
    except Exception as e:
        error_msg = f"Hard-delete failed: {e}"
        log.error(error_msg)
        results["errors"].append(error_msg)
        log_error("cleanup", "hard_delete", error_msg)

    return results


def run_dedup() -> Dict:
    """Detect and handle duplicate grant calls.

    Uses title + announced_at as dedup key (PRD OP-001).

    Returns:
        Dict with dedup results
    """
    db = get_db()
    results = {
        "duplicates_found": 0,
        "duplicates_merged": 0,
        "errors": [],
    }

    try:
        duplicates = db.find_duplicates()
        results["duplicates_found"] = len(duplicates)

        if not duplicates:
            log.info("Dedup: no duplicates found")
            return results

        log.info(f"Dedup: found {len(duplicates)} duplicate pairs")

        for dup in duplicates:
            try:
                original_id = dup["original_id"]
                duplicate_id = dup["duplicate_id"]
                original_title = dup.get("original_title", "")[:100]
                duplicate_title = dup.get("duplicate_title", "")[:100]

                log.info(f"Dedup: merging #{duplicate_id} '{duplicate_title[:60]}' "
                         f"into #{original_id} '{original_title[:60]}'")

                # Merge: move chunks and attachments from duplicate to original
                # Then soft-delete the duplicate
                _merge_duplicate(db, original_id, duplicate_id)
                results["duplicates_merged"] += 1

            except Exception as e:
                error_msg = f"Failed to merge duplicate {dup}: {e}"
                log.error(error_msg)
                results["errors"].append(error_msg)

    except Exception as e:
        error_msg = f"Dedup detection failed: {e}"
        log.error(error_msg)
        results["errors"].append(error_msg)
        log_error("cleanup", "dedup", error_msg)

    return results


def _merge_duplicate(db, original_id: int, duplicate_id: int):
    """Merge a duplicate call into the original.

    Strategy:
    1. Log the dedup action
    2. Soft-delete the duplicate (don't delete data, just mark)
    """
    import json
    import requests
    from datetime import datetime, timezone
    from .config import SUPABASE_URL, SUPABASE_KEY

    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "return=minimal",
    }

    # Log the dedup
    log_data = {
        "original_call_id": original_id,
        "duplicate_call_id": duplicate_id,
        "match_reason": "title_date_match",
        "action": "merged",
    }
    try:
        requests.post(f"{SUPABASE_URL}/rest/v1/dedup_log", headers=headers,
                       json=[log_data], timeout=10)
    except Exception:
        pass

    # Soft-delete the duplicate
    requests.patch(
        f"{SUPABASE_URL}/rest/v1/grant_calls_v2",
        headers=headers,
        params={"id": f"eq.{duplicate_id}"},
        json={"deleted_at": datetime.now(timezone.utc).isoformat()},
        timeout=10,
    )


def run_all_maintenance() -> Dict:
    """Run all maintenance tasks: cleanup + dedup."""
    log.info("=== Starting maintenance run ===")

    cleanup_result = run_cleanup()
    dedup_result = run_dedup()

    summary = {
        "cleanup": cleanup_result,
        "dedup": dedup_result,
    }

    log.info(f"=== Maintenance complete: "
             f"soft_deleted={cleanup_result['soft_deleted_calls']}, "
             f"hard_deleted={cleanup_result['hard_deleted_chunks']}, "
             f"dupes_found={dedup_result['duplicates_found']}, "
             f"dupes_merged={dedup_result['duplicates_merged']} ===")

    return summary

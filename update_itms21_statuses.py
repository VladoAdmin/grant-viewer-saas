#!/usr/bin/env python3
"""
update_itms21_statuses.py

Aktualizuje statusy ITMS21 výziev na základe deadline_at.
- Ak deadline_at >= dnes → "Otvorená"
- Ak deadline_at < dnes → "Uzavretá"
"""

import os
import sys
import requests
from datetime import datetime, timezone
from dotenv import load_dotenv
from pathlib import Path

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_SERVICE_ROLE_KEY"]

SB_HEADERS_MIN = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json",
    "Prefer": "return=minimal",
}

SB_HEADERS_REPR = {**SB_HEADERS_MIN, "Prefer": "return=representation"}


def get_itms21_calls():
    """Get all ITMS21 calls with their deadline_at"""
    calls = []
    offset = 0
    while True:
        params = {
            "select": "id,title,status,deadline_at",
            "source": "eq.portal.itms21.sk",
            "offset": str(offset),
            "limit": "1000",
        }
        r = requests.get(f"{SUPABASE_URL}/rest/v1/grant_calls_v2", headers=SB_HEADERS_MIN, params=params)
        r.raise_for_status()
        batch = r.json()
        calls.extend(batch)
        if len(batch) < 1000:
            break
        offset += 1000
    return calls


def update_call_status(call_id: str, new_status: str) -> bool:
    """Update the status of a call"""
    try:
        r = requests.patch(
            f"{SUPABASE_URL}/rest/v1/grant_calls_v2",
            headers=SB_HEADERS_MIN,
            params={"id": f"eq.{call_id}"},
            json={"status": new_status},
        )
        r.raise_for_status()
        return True
    except Exception as e:
        print(f"Error updating {call_id}: {e}")
        return False


def main():
    today = datetime.now(timezone.utc).date()
    print(f"Today: {today}")
    print("Fetching ITMS21 calls...")

    calls = get_itms21_calls()
    print(f"Found {len(calls)} ITMS21 calls")

    to_open = []
    to_close = []

    for call in calls:
        call_id = call["id"]
        current_status = call.get("status", "")
        deadline_at = call.get("deadline_at")

        if deadline_at:
            # Parse deadline
            try:
                deadline_date = datetime.fromisoformat(deadline_at.replace("Z", "+00:00")).date()

                if deadline_date >= today and current_status != "Otvorená":
                    to_open.append((call_id, call.get("title", "")[:60], deadline_date))
                elif deadline_date < today and current_status != "Uzavretá":
                    to_close.append((call_id, call.get("title", "")[:60], deadline_date))
            except Exception as e:
                print(f"Error parsing deadline for {call_id}: {e}")
        else:
            # No deadline - mark as closed if not already
            if current_status != "Uzavretá":
                to_close.append((call_id, call.get("title", "")[:60], None))

    print(f"\nCalls to mark as OPEN: {len(to_open)}")
    for call_id, title, deadline in to_open:
        print(f"  - {call_id}: {title} (deadline: {deadline})")

    print(f"\nCalls to mark as CLOSED: {len(to_close)}")
    for call_id, title, deadline in to_close:
        print(f"  - {call_id}: {title} (deadline: {deadline})")

    # Confirm before updating
    if not to_open and not to_close:
        print("\nNo status updates needed.")
        return 0

    print("\nUpdating statuses...")
    updated = 0

    for call_id, title, _ in to_open:
        if update_call_status(call_id, "Otvorená"):
            updated += 1
            print(f"  ✓ {call_id} → Otvorená")

    for call_id, title, _ in to_close:
        if update_call_status(call_id, "Uzavretá"):
            updated += 1
            print(f"  ✓ {call_id} → Uzavretá")

    print(f"\nUpdated {updated} calls")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

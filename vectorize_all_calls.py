#!/usr/bin/env python3
"""
vectorize_all_calls.py

Vektorizuje všetky grantové výzvy bez ohľadu na status.
Reportuje progress každých 20 výziev.
"""

import subprocess
import json
import time
import sys
import os

def run_vectorization():
    """Run the attachment analyzer and monitor progress"""
    print("=== Starting vectorization of all grant calls ===")
    print("Processing ~307 calls with PDF attachments...")
    print("")

    # Run attachment analyzer
    process = subprocess.Popen(
        ["python3", "attachment_analyzer.py", "--batch-size", "5"],
        cwd="/home/clawd/Projects/grant-scraper/v2",
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1
    )

    calls_processed = 0
    calls_total = 307
    pdfs_downloaded = 0
    chunks_created = 0
    pdfs_failed = 0
    last_report = 0

    print("Progress report every 20 calls:")
    print("-" * 60)

    for line in process.stdout:
        line = line.strip()

        # Parse progress from log lines
        if "Progress(" in line or '"calls_processed"' in line:
            try:
                # Try to extract JSON stats
                if "{" in line:
                    json_start = line.find("{")
                    stats = json.loads(line[json_start:])
                    calls_processed = stats.get("calls_processed", calls_processed)
                    pdfs_downloaded = stats.get("pdfs_ok", pdfs_downloaded)
                    chunks_created = stats.get("chunks_created", chunks_created)
                    pdfs_failed = stats.get("pdfs_failed", pdfs_failed)

                    # Report every 20 calls
                    if calls_processed >= last_report + 20:
                        last_report = (calls_processed // 20) * 20
                        print(f"[{time.strftime('%H:%M:%S')}] Progress: {calls_processed}/{calls_total} calls, "
                              f"{pdfs_downloaded} PDFs OK, {pdfs_failed} failed, {chunks_created} chunks")
            except Exception:
                pass

        # Print batch info
        if "--- Batch" in line:
            print(line)

        # Print call info
        if "Call:" in line and "PDFs=" in line:
            print(f"  {line}")

    process.wait()

    print("-" * 60)
    print(f"\n=== Vectorization complete ===")
    print(f"Calls processed: {calls_processed}")
    print(f"PDFs downloaded: {pdfs_downloaded}")
    print(f"PDFs failed: {pdfs_failed}")
    print(f"Chunks created: {chunks_created}")

    return process.returncode


if __name__ == "__main__":
    sys.exit(run_vectorization())

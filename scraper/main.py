#!/usr/bin/env python3
"""Grant Viewer SaaS — Scraper CLI.

Usage:
    python -m scraper.main scrape [--source itms21] [--limit 200]
    python -m scraper.main embed [--call-id 123] [--all] [--dry-run]
    python -m scraper.main cleanup [--months 12]
    python -m scraper.main dedup
    python -m scraper.main export-pdf --call-id 123 --output call.pdf
    python -m scraper.main status
"""

import argparse
import json
import logging
import sys
from pathlib import Path

# Ensure project root is on path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from scraper.config import LOG_LEVEL, validate_config
from scraper.db import get_db
from scraper.error_handler import ErrorCollector, log_error

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    handlers=[logging.StreamHandler()],
)
log = logging.getLogger("scraper")


def cmd_scrape(args):
    """Run scraper for specified source."""
    from scraper.handlers.itms21 import ITMS21Handler

    handlers = {
        "itms21": ITMS21Handler,
    }

    source = args.source.lower()
    if source not in handlers:
        log.error(f"Unknown source: {source}. Available: {list(handlers.keys())}")
        return 1

    handler = handlers[source]()
    result = handler.scrape(limit=args.limit)

    print(f"\n{'='*50}")
    print(f"Source: {result.source}")
    print(f"Found: {result.calls_found}")
    print(f"New: {result.calls_new}")
    print(f"Updated: {result.calls_updated}")
    print(f"Errors: {len(result.errors)}")
    print(f"Duration: {result.duration_seconds:.1f}s")
    print(f"{'='*50}")

    return 1 if result.errors else 0


def cmd_embed(args):
    """Run embedding for grant calls."""
    from scraper.embedder.embedder import embed_and_store
    from scraper.extractor.zip_handler import extract_from_url
    from scraper.extractor.classifier import classify_document
    from scraper.extractor.attribute_extractor import extract_attributes

    db = get_db()
    collector = ErrorCollector("embedder")

    if args.call_id:
        calls = [db.get_grant_call_by_id(args.call_id)]
        calls = [c for c in calls if c]
    else:
        calls = db.get_grant_calls(source="portal.itms21.sk", limit=args.limit or 1000)

    if not calls:
        print("No calls found to embed")
        return 0

    total_chunks = 0
    for i, call in enumerate(calls):
        call_id = call["id"]
        title = (call.get("title") or "")[:80]

        # Skip if already embedded (unless --force)
        if not args.force:
            existing = db._get("v2_call_chunks", {
                "call_id": f"eq.{call_id}", "select": "id", "limit": "1"
            })
            if existing:
                log.info(f"[{i+1}/{len(calls)}] Skipping {title} (already embedded)")
                continue

        log.info(f"[{i+1}/{len(calls)}] Processing: {title}")

        with collector.catch(component="embed", call_id=call_id):
            # Get attachments
            attachments = db.get_attachments(call_id)
            if not attachments:
                log.info(f"  No attachments for call {call_id}")
                continue

            # Extract documents
            documents = []
            for att in attachments:
                url = att.get("url", "")
                if not url:
                    continue

                # Skip non-PDF file types
                name_lower = (att.get("name") or "").lower()
                skip_exts = ('.jpg', '.jpeg', '.png', '.gif', '.csv', '.xml', '.html')
                if any(name_lower.endswith(ext) for ext in skip_exts):
                    continue

                extracted = extract_from_url(url)
                for doc in extracted:
                    doc_type, confidence = classify_document(doc.filename, doc.text[:4000])
                    if doc_type == "skip":
                        continue
                    documents.append({
                        "text": doc.text,
                        "filename": doc.filename,
                        "doc_type": doc_type,
                        "source_url": doc.source_url,
                    })

            if documents:
                # --- Attribute extraction (before chunking) ---
                try:
                    pdf_attrs = extract_attributes(documents)
                    if pdf_attrs:
                        # Get existing API attributes (fallback)
                        api_attrs = db.get_attributes(call_id)

                        # Merge: API is base, PDF overwrites (PDF has priority)
                        merged_attrs = {**api_attrs, **pdf_attrs}

                        # Update grant_calls_v2 columns from extracted attributes
                        call_update = {}
                        if pdf_attrs.get("datum_vyhlasenia"):
                            call_update["announced_at"] = pdf_attrs["datum_vyhlasenia"]
                        if pdf_attrs.get("celkova_alokacia"):
                            call_update["total_allocation"] = pdf_attrs["celkova_alokacia"]
                        if pdf_attrs.get("deadline"):
                            # Only set deadline_at if it's a proper date (YYYY-MM-DD)
                            import re as _re
                            if _re.match(r'^\d{4}-\d{2}-\d{2}$', pdf_attrs["deadline"]):
                                call_update["deadline_at"] = pdf_attrs["deadline"]
                        if pdf_attrs.get("poskytovatel"):
                            call_update["provider"] = pdf_attrs["poskytovatel"][:500]

                        if call_update:
                            db.update_grant_call(call_id, call_update)

                        # Save all attributes (merged)
                        db.save_attributes(call_id, merged_attrs)
                        log.info(f"  Attributes: {len(pdf_attrs)} from PDF, "
                                 f"{len(merged_attrs)} total (merged with API)")
                except Exception as e:
                    log.warning(f"  Attribute extraction failed for call {call_id}: {e}")

                # --- Chunking and embedding ---
                n = embed_and_store(call_id, title, documents, dry_run=args.dry_run)
                total_chunks += n
                log.info(f"  Created {n} chunks")
            else:
                log.info(f"  No extractable documents")

    print(f"\nTotal chunks created: {total_chunks}")
    if collector.has_errors:
        print(f"Errors: {collector.summary()}")
    return 0


def cmd_cleanup(args):
    """Run cleanup and dedup."""
    from scraper.cleanup import run_cleanup, run_dedup

    if args.dedup_only:
        result = run_dedup()
    else:
        cleanup = run_cleanup(months_threshold=args.months)
        dedup = run_dedup()
        result = {"cleanup": cleanup, "dedup": dedup}

    print(json.dumps(result, indent=2, default=str))
    return 0


def cmd_export_pdf(args):
    """Export a grant call as PDF."""
    from scraper.pdf_export import generate_call_pdf

    db = get_db()
    call = db.get_grant_call_by_id(args.call_id)
    if not call:
        print(f"Call {args.call_id} not found")
        return 1

    attributes = db.get_attributes(args.call_id)
    attachments = db.get_attachments(args.call_id)

    pdf_bytes = generate_call_pdf(call, attributes, attachments)
    if not pdf_bytes:
        print("Failed to generate PDF (install reportlab or fpdf2)")
        return 1

    output = args.output or f"call_{args.call_id}.pdf"
    Path(output).write_bytes(pdf_bytes)
    print(f"PDF exported: {output} ({len(pdf_bytes)} bytes)")
    return 0


def cmd_enrich(args):
    """Enrich existing chunks with metadata and re-embed."""
    from scraper.embedder.embedder import enrich_existing_chunks

    db = get_db()

    if args.call_id:
        call_ids = [args.call_id]
    elif args.all:
        # Get all unique call_ids with chunks
        result = db._get("v2_call_chunks", {
            "select": "call_id",
            "deleted_at": "is.null",
            "order": "call_id.asc",
        })
        call_ids = sorted(set(r["call_id"] for r in result))
    else:
        print("Specify --call-id or --all")
        return 1

    total = 0
    for i, cid in enumerate(call_ids):
        log.info(f"[{i + 1}/{len(call_ids)}] Enriching call_id={cid}...")
        n = enrich_existing_chunks(cid)
        total += n
        log.info(f"  Enriched {n} chunks")

    print(f"\nTotal enriched chunks: {total}")
    return 0


def cmd_status(args):
    """Show scraper status."""
    db = get_db()
    runs = db.get_last_scraper_runs(limit=5)

    if runs:
        print(f"\n{'Source':<20} {'Status':<10} {'Found':<8} {'New':<6} {'Started':<25}")
        print("-" * 75)
        for run in runs:
            print(f"{run.get('source', ''):<20} "
                  f"{run.get('status', ''):<10} "
                  f"{run.get('calls_found', 0):<8} "
                  f"{run.get('calls_new', 0):<6} "
                  f"{run.get('started_at', '')[:19]:<25}")
    else:
        print("No scraper runs recorded yet")

    # Also show call counts
    calls = db.get_grant_calls(limit=10000)
    sources = {}
    for c in calls:
        src = c.get("source", "unknown")
        sources[src] = sources.get(src, 0) + 1

    print(f"\nTotal calls in DB: {len(calls)}")
    for src, cnt in sorted(sources.items()):
        print(f"  {src}: {cnt}")

    return 0


def main():
    parser = argparse.ArgumentParser(description="Grant Viewer SaaS — Scraper CLI")
    sub = parser.add_subparsers(dest="command")

    # Scrape
    scrape_p = sub.add_parser("scrape", help="Scrape grant calls")
    scrape_p.add_argument("--source", default="itms21", help="Source (itms21)")
    scrape_p.add_argument("--limit", type=int, default=200, help="Max calls")

    # Embed
    embed_p = sub.add_parser("embed", help="Embed grant call documents")
    embed_p.add_argument("--call-id", type=int, help="Specific call ID")
    embed_p.add_argument("--limit", type=int, help="Max calls to process")
    embed_p.add_argument("--force", action="store_true", help="Re-embed existing")
    embed_p.add_argument("--dry-run", action="store_true", help="Skip actual embedding")

    # Enrich
    enrich_p = sub.add_parser("enrich", help="Enrich existing chunks with metadata + re-embed")
    enrich_p.add_argument("--call-id", type=int, help="Specific call ID")
    enrich_p.add_argument("--all", action="store_true", help="Enrich all calls")

    # Cleanup
    cleanup_p = sub.add_parser("cleanup", help="Run cleanup + dedup")
    cleanup_p.add_argument("--months", type=int, default=12, help="Months threshold")
    cleanup_p.add_argument("--dedup-only", action="store_true", help="Only run dedup")

    # Export PDF
    export_p = sub.add_parser("export-pdf", help="Export call as PDF")
    export_p.add_argument("--call-id", type=int, required=True, help="Call ID")
    export_p.add_argument("--output", type=str, help="Output file path")

    # Status
    sub.add_parser("status", help="Show scraper status")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return 0

    # Validate config
    errors = validate_config()
    if errors and args.command not in ("status",):
        for e in errors:
            log.warning(f"Config: {e}")

    commands = {
        "scrape": cmd_scrape,
        "embed": cmd_embed,
        "enrich": cmd_enrich,
        "cleanup": cmd_cleanup,
        "export-pdf": cmd_export_pdf,
        "status": cmd_status,
    }

    return commands[args.command](args)


if __name__ == "__main__":
    sys.exit(main())

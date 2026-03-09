#!/usr/bin/env python3
"""
vectorize_calls_v3.py - Vectorize ALL 362 grant calls including ZIP handling for ITMS21.

Features:
- Downloads PDFs directly or extracts them from ZIP archives
- Handles all sources (ITMS21, planobnovy, apvv, etc.)
- Chunks text (512-1024 tokens), generates embeddings
- Upserts to v2_call_chunks in Supabase
- Reports progress every 10 calls
- Resumable via state file
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import logging
import os
import re
import tempfile
import time
import zipfile
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import signal
import pdfplumber
import requests
import tiktoken
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

# Config
PDF_CACHE_DIR = Path("/tmp/grant_attachments_v3")
PDF_CACHE_DIR.mkdir(parents=True, exist_ok=True)
STATE_FILE = PDF_CACHE_DIR / "vectorize_state.json"
LOG_FILE = PDF_CACHE_DIR / "vectorize.log"

CHUNK_TARGET = 768
CHUNK_MAX = 1024
CHUNK_MIN = 256
EMBED_MODEL = "text-embedding-3-small"
EMBED_BATCH = 96

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
OPENAI_KEY = os.environ["OPENAI_API_KEY"]

SB_H = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json",
    "Prefer": "return=minimal",
}

oai = OpenAI(api_key=OPENAI_KEY, timeout=60.0)
enc = tiktoken.encoding_for_model("gpt-4")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[logging.StreamHandler(), logging.FileHandler(LOG_FILE)],
)
log = logging.getLogger("vectorize_v3")
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("openai").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)


# ---- Supabase helpers ----

def sb_get(table, select="*", filters=None, limit=1000):
    out, offset = [], 0
    while True:
        params = {"select": select, "offset": str(offset), "limit": str(limit)}
        if filters:
            params.update(filters)
        r = requests.get(f"{SUPABASE_URL}/rest/v1/{table}", headers=SB_H, params=params, timeout=60)
        r.raise_for_status()
        batch = r.json()
        out.extend(batch)
        if len(batch) < limit:
            break
        offset += limit
    return out


def sb_upsert(table, rows, dry_run=False):
    if not rows or dry_run:
        return
    headers = {**SB_H, "Prefer": "resolution=merge-duplicates,return=minimal"}
    for i in range(0, len(rows), 20):
        batch = rows[i:i+20]
        r = requests.post(f"{SUPABASE_URL}/rest/v1/{table}", headers=headers, json=batch, timeout=180)
        if r.status_code >= 400:
            log.error(f"Upsert error {r.status_code}: {r.text[:300]}")
            r.raise_for_status()


def sb_chunk_exists(call_id, source_url):
    r = requests.get(f"{SUPABASE_URL}/rest/v1/v2_call_chunks", headers=SB_H,
                     params={"select": "id", "call_id": f"eq.{call_id}", "source_url": f"eq.{source_url}", "limit": "1"}, timeout=30)
    return r.status_code == 200 and len(r.json()) > 0


def ensure_enriched_stub(call_id, title, dry_run=False):
    r = requests.get(f"{SUPABASE_URL}/rest/v1/v2_enriched_calls", headers=SB_H,
                     params={"select": "id", "id": f"eq.{call_id}", "limit": "1"}, timeout=30)
    r.raise_for_status()
    if r.json():
        return
    stub = {"id": call_id, "title_clean": title[:500], "enrichment_status": "pending"}
    if not dry_run:
        r2 = requests.post(f"{SUPABASE_URL}/rest/v1/v2_enriched_calls", headers=SB_H, json=stub, timeout=30)
        if r2.status_code >= 400:
            log.error(f"Stub creation failed: {r2.text[:300]}")


# ---- PDF/ZIP download & extraction ----

def _cache_path(url):
    return PDF_CACHE_DIR / (hashlib.md5(url.encode()).hexdigest() + ".pdf")


def download_content(url, timeout=30, max_mb=50):
    """Download URL, return (bytes, content_type). Skip files > max_mb."""
    try:
        r = requests.get(url, timeout=timeout, headers={"User-Agent": "Mozilla/5.0"}, stream=True)
        r.raise_for_status()
        ct = (r.headers.get("content-type") or "").lower()
        cl = int(r.headers.get("content-length", 0))
        if cl > max_mb * 1024 * 1024:
            log.warning(f"Skip too large ({cl/1024/1024:.1f}MB): {url}")
            return None, None
        content = b""
        for chunk in r.iter_content(chunk_size=65536):
            content += chunk
            if len(content) > max_mb * 1024 * 1024:
                log.warning(f"Download exceeded {max_mb}MB, truncating: {url}")
                return None, None
        return content, ct
    except Exception as e:
        log.warning(f"Download failed {url}: {e}")
        return None, None


def extract_pdfs_from_content(content, content_type, url) -> List[Tuple[Path, str]]:
    """Returns list of (pdf_path, source_label). Handles direct PDF or ZIP with PDFs inside."""
    results = []

    if content is None:
        return results

    # Direct PDF
    if "pdf" in content_type or content[:5] == b"%PDF-":
        path = _cache_path(url)
        if not path.exists():
            path.write_bytes(content)
        results.append((path, url))
        return results

    # ZIP file
    if "zip" in content_type or content[:2] == b"PK":
        try:
            with zipfile.ZipFile(io.BytesIO(content)) as zf:
                for name in zf.namelist():
                    if name.lower().endswith(".pdf") and not name.startswith("__MACOSX"):
                        pdf_bytes = zf.read(name)
                        if len(pdf_bytes) < 100:
                            continue
                        label = f"{url}#{name}"
                        path = _cache_path(label)
                        if not path.exists():
                            path.write_bytes(pdf_bytes)
                        results.append((path, label))
        except Exception as e:
            log.warning(f"ZIP extraction failed {url}: {e}")
        return results

    # Unknown type - try as PDF anyway
    if content[:5] == b"%PDF-":
        path = _cache_path(url)
        if not path.exists():
            path.write_bytes(content)
        results.append((path, url))

    return results


def extract_text(pdf_path):
    import threading
    result = [None]
    def _extract():
        try:
            parts = []
            with pdfplumber.open(str(pdf_path)) as pdf:
                for page in pdf.pages[:100]:  # limit pages
                    t = page.extract_text()
                    if t:
                        parts.append(t)
            text = "\n\n".join(parts).strip()
            result[0] = text if len(text) >= 50 else None
        except Exception as e:
            log.warning(f"pdfplumber failed {pdf_path.name}: {e}")
    
    t = threading.Thread(target=_extract)
    t.start()
    t.join(timeout=60)  # 60s max for PDF extraction
    if t.is_alive():
        log.warning(f"pdfplumber timeout {pdf_path.name}")
        return None
    return result[0]


# ---- Chunking & Embeddings ----

def ntokens(text):
    return len(enc.encode(text))


def chunk_text(text):
    paragraphs = [p.strip() for p in re.split(r"\n+", text) if p.strip()]
    chunks, cur, cur_t = [], [], 0

    for p in paragraphs:
        pt = ntokens(p)
        if pt > CHUNK_MAX:
            if cur:
                chunks.append("\n".join(cur))
                cur, cur_t = [], 0
            sents = re.split(r"(?<=[\.\!\?])\s+", p)
            tmp, tmp_t = [], 0
            for s in sents:
                st = ntokens(s)
                if tmp and tmp_t + st > CHUNK_MAX:
                    chunks.append(" ".join(tmp))
                    tmp, tmp_t = [], 0
                tmp.append(s)
                tmp_t += st
            if tmp:
                chunks.append(" ".join(tmp))
            continue
        if cur and cur_t + pt > CHUNK_TARGET:
            chunks.append("\n".join(cur))
            cur, cur_t = [], 0
        cur.append(p)
        cur_t += pt

    if cur:
        chunks.append("\n".join(cur))

    # merge tiny chunks
    merged = []
    for c in chunks:
        if merged and ntokens(merged[-1]) + ntokens(c) < CHUNK_MIN * 2:
            merged[-1] += "\n" + c
        else:
            merged.append(c)
    return merged


def embed_texts(texts):
    if not texts:
        return []
    out = []
    for i in range(0, len(texts), EMBED_BATCH):
        batch = texts[i:i+EMBED_BATCH]
        for attempt in range(5):
            try:
                resp = oai.embeddings.create(model=EMBED_MODEL, input=batch)
                out.extend([d.embedding for d in resp.data])
                break
            except Exception as e:
                w = min(60, 2 ** (attempt + 1))
                log.warning(f"Embed error attempt {attempt+1}: {e} (sleep {w}s)")
                time.sleep(w)
                if attempt == 4:
                    out.extend([[0.0] * 1536 for _ in batch])
    return out


# ---- ITMS21 specific ----

def get_itms21_docs(call_url):
    """Fetch document list from ITMS21 API for a call."""
    m = re.search(r"[?&]id=(\d+)", call_url or "")
    if not m:
        return []
    itms_id = m.group(1)
    try:
        r = requests.get(f"https://api.itms21.sk/public/v1/vyzva/id/{itms_id}",
                         timeout=30, headers={"Accept": "application/json"})
        r.raise_for_status()
        docs = r.json().get("dokument") or []
        return [{"name": d.get("nazov", ""), "uuid": d.get("uuid", "")} for d in docs if isinstance(d, dict) and d.get("uuid")]
    except Exception as e:
        log.warning(f"ITMS21 API failed for {call_url}: {e}")
        return []


# ---- Attachment resolution per source ----

def get_attachments_for_call(call):
    """Returns list of download URLs for a call."""
    source = call.get("source", "")
    call_id = call["id"]

    if source == "portal.itms21.sk":
        docs = get_itms21_docs(call.get("call_url"))
        return [{"name": d["name"], "url": f"https://api.itms21.sk/public/v1/dokument/{d['uuid']}"} for d in docs]

    # For other sources: check grant_calls_v2.attachments JSONB, then grant_call_attachments table
    try:
        r = requests.get(f"{SUPABASE_URL}/rest/v1/grant_calls_v2", headers=SB_H,
                         params={"select": "attachments", "id": f"eq.{call_id}", "limit": "1"}, timeout=30)
        if r.status_code == 200 and r.json():
            atts = r.json()[0].get("attachments")
            if isinstance(atts, list) and atts:
                return [{"name": a.get("name", "att"), "url": a.get("url") or a.get("href", "")}
                        for a in atts if isinstance(a, dict) and (a.get("url") or a.get("href"))]
    except Exception:
        pass

    # Fallback: attachments table
    rows = sb_get("grant_call_attachments", select="name,url,file_type",
                   filters={"grant_call_id": f"eq.{call_id}"}, limit=100)
    return [{"name": r.get("name", "att"), "url": r["url"]} for r in rows if r.get("url")]


# ---- State management ----

def load_state():
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except Exception:
            pass
    return {"processed_ids": [], "stats": {}}


def save_state(state):
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=1))


# ---- Main ----

@dataclass
class Stats:
    calls_processed: int = 0
    calls_skipped: int = 0
    calls_no_docs: int = 0
    calls_failed: int = 0
    pdfs_ok: int = 0
    pdfs_failed: int = 0
    chunks_created: int = 0
    zips_extracted: int = 0

    def dict(self):
        return {k: v for k, v in self.__dict__.items()}


def process_call(call, stats, dry_run=False):
    """Process one call. Returns number of chunks created."""
    call_id = call["id"]
    title = (call.get("title") or "")[:100]
    
    attachments = get_attachments_for_call(call)
    if not attachments:
        stats.calls_no_docs += 1
        return 0

    try:
        ensure_enriched_stub(call_id, call.get("title", ""), dry_run=dry_run)
    except Exception as e:
        log.error(f"Stub failed for {call_id}: {e}")
        stats.calls_failed += 1
        return 0

    total_chunks = 0
    all_rows = []
    call_pdfs_ok = 0
    log.debug(f"  Attachments: {len(attachments)}")

    for ai, att in enumerate(attachments):
        url = att.get("url", "")
        if not url:
            continue

        # Skip obviously non-PDF files by extension
        name_lower = (att.get("name", "") or "").lower()
        skip_exts = ('.docx', '.doc', '.xlsx', '.xls', '.pptx', '.ppt', '.jpg', '.jpeg', '.png', '.gif', '.csv', '.xml', '.html')
        if any(name_lower.endswith(ext) for ext in skip_exts):
            log.debug(f"  [{ai+1}/{len(attachments)}] Skipping non-PDF: {name_lower[:60]}")
            continue

        log.info(f"  [{ai+1}/{len(attachments)}] Downloading {att.get('name','')[:60]}...")
        # Download
        content, ct = download_content(url)
        if content is None:
            stats.pdfs_failed += 1
            continue
        log.info(f"  [{ai+1}] Downloaded {len(content)/1024:.0f}KB, type={ct[:30]}")

        # Extract PDFs (handles ZIP)
        is_zip = "zip" in ct or (content[:2] == b"PK")
        pdf_files = extract_pdfs_from_content(content, ct, url)
        if is_zip:
            stats.zips_extracted += 1

        if not pdf_files:
            if not is_zip:  # ZIPs without PDFs aren't really failures
                stats.pdfs_failed += 1
            continue

        for pdf_path, source_label in pdf_files:
            if sb_chunk_exists(call_id, source_label):
                call_pdfs_ok += 1
                stats.pdfs_ok += 1
                continue

            text = extract_text(pdf_path)
            if not text:
                stats.pdfs_failed += 1
                continue

            chunks = chunk_text(text)
            if not chunks:
                stats.pdfs_failed += 1
                continue

            log.info(f"  [{ai+1}] Embedding {len(chunks)} chunks...")
            embeddings = embed_texts(chunks) if not dry_run else [[0.0]*1536 for _ in chunks]
            log.info(f"  [{ai+1}] Embedding done")

            for idx, (ch, emb) in enumerate(zip(chunks, embeddings)):
                all_rows.append({
                    "call_id": call_id,
                    "source_type": "pdf",
                    "source_url": source_label,
                    "chunk_index": idx,
                    "chunk_text": ch,
                    "token_count": ntokens(ch),
                    "embedding": json.dumps(emb),
                })

            call_pdfs_ok += 1
            stats.pdfs_ok += 1
            total_chunks += len(chunks)

    if all_rows:
        log.info(f"  Upserting {len(all_rows)} chunks to Supabase...")
        try:
            sb_upsert("v2_call_chunks", all_rows, dry_run=dry_run)
            stats.chunks_created += len(all_rows)
            log.info(f"  Upsert done")
        except Exception as e:
            log.error(f"Insert failed for {call_id}: {e}")
            stats.calls_failed += 1
            return 0

    if call_pdfs_ok > 0:
        stats.calls_processed += 1
    else:
        stats.calls_failed += 1

    return total_chunks


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--max-calls", type=int, default=0)
    ap.add_argument("--fresh", action="store_true", help="Ignore previous state, start fresh")
    args = ap.parse_args()

    log.info("=== Vectorize v3 starting ===")

    # Load all calls
    calls = sb_get("grant_calls_v2", select="id,title,source,call_url,status,deadline_at", limit=1000)
    log.info(f"Total calls in DB: {len(calls)}")

    sources = Counter(c.get("source") for c in calls)
    for s, cnt in sources.most_common():
        log.info(f"  {s}: {cnt}")

    # Load state
    state = load_state() if not args.fresh else {"processed_ids": [], "stats": {}}
    done_ids = set(state.get("processed_ids", []))
    log.info(f"Previously processed: {len(done_ids)}")

    # Filter out already processed
    remaining = [c for c in calls if c["id"] not in done_ids]
    if args.max_calls:
        remaining = remaining[:args.max_calls]
    log.info(f"Remaining to process: {len(remaining)}")

    stats = Stats()
    start_time = time.time()

    for i, call in enumerate(remaining):
        title = (call.get("title") or "")[:80]
        source = call.get("source", "")
        
        def _timeout_handler(signum, frame):
            raise TimeoutError("Call processing exceeded 120s")
        
        old_handler = signal.signal(signal.SIGALRM, _timeout_handler)
        signal.alarm(120)  # 2 min max per call
        try:
            n = process_call(call, stats, dry_run=args.dry_run)
            log.info(f"[{i+1}/{len(remaining)}] {source}: {title} -> {n} chunks")
        except TimeoutError:
            log.error(f"[{i+1}/{len(remaining)}] TIMEOUT {title}")
            stats.calls_failed += 1
        except Exception as e:
            log.error(f"[{i+1}/{len(remaining)}] FAILED {title}: {e}")
            stats.calls_failed += 1
        finally:
            signal.alarm(0)
            signal.signal(signal.SIGALRM, old_handler)

        done_ids.add(call["id"])

        # Report every 10
        if (i + 1) % 10 == 0:
            elapsed = time.time() - start_time
            rate = (i + 1) / elapsed * 60 if elapsed > 0 else 0
            log.info(f"=== PROGRESS {i+1}/{len(remaining)} ({rate:.1f} calls/min) ===")
            log.info(f"  Processed: {stats.calls_processed}, No docs: {stats.calls_no_docs}, Failed: {stats.calls_failed}")
            log.info(f"  PDFs OK: {stats.pdfs_ok}, PDFs failed: {stats.pdfs_failed}, ZIPs: {stats.zips_extracted}")
            log.info(f"  Chunks created: {stats.chunks_created}")

        # Save state every 5 calls
        if (i + 1) % 5 == 0:
            state["processed_ids"] = list(done_ids)
            state["stats"] = stats.dict()
            state["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            save_state(state)

    # Final save
    state["processed_ids"] = list(done_ids)
    state["stats"] = stats.dict()
    state["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    save_state(state)

    elapsed = time.time() - start_time
    log.info("=" * 60)
    log.info("=== FINAL REPORT ===")
    log.info(f"Time: {elapsed/60:.1f} minutes")
    log.info(f"Calls processed: {stats.calls_processed}")
    log.info(f"Calls no docs: {stats.calls_no_docs}")
    log.info(f"Calls skipped (already done): {len(done_ids) - len(remaining)}")
    log.info(f"Calls failed: {stats.calls_failed}")
    log.info(f"PDFs OK: {stats.pdfs_ok}")
    log.info(f"PDFs failed: {stats.pdfs_failed}")
    log.info(f"ZIPs extracted: {stats.zips_extracted}")
    log.info(f"Chunks created: {stats.chunks_created}")
    log.info("=" * 60)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

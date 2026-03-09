#!/usr/bin/env python3
"""/home/clawd/Projects/grant-scraper/v2/attachment_analyzer.py

Cieľ: Pre každú výzvu stiahnuť PDF prílohy, extrahovať text (pdfplumber; fallback OCR),
chunkovať (512-1024 tokenov), vytvoriť embeddings (text-embedding-3-small) a uložiť do
`v2_call_chunks` pre kontextové vyhľadávanie.

Poznámka k DB schéme:
- `v2_call_chunks.call_id` má FK na `v2_enriched_calls.id` (nie priamo na grant_calls_v2).
  Preto skript pred spracovaním výzvy zabezpečí existenciu „stub“ riadku v `v2_enriched_calls`
  so statusom `pending`.

Spúšťanie:
  cd /home/clawd/Projects/grant-scraper/v2
  python3 attachment_analyzer.py --batch-size 20 --max-calls 0

Bezpečný režim (dry run):
  python3 attachment_analyzer.py --dry-run
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

import requests
import tiktoken
import pdfplumber
from dotenv import load_dotenv
from openai import OpenAI

# Load env from repo root (/home/clawd/Projects/grant-scraper/.env)
load_dotenv(Path(__file__).resolve().parents[1] / ".env")


# -------------------- Config --------------------
PDF_CACHE_DIR = Path("/tmp/grant_attachments")
PDF_CACHE_DIR.mkdir(parents=True, exist_ok=True)

DOWNLOAD_TIMEOUT_S = 60

CHUNK_TARGET_TOKENS = 768
CHUNK_MAX_TOKENS = 1024
CHUNK_MIN_TOKENS = 256

EMBED_MODEL = "text-embedding-3-small"  # 1536 dim - OpenAI fallback
OLLAMA_MODEL = "nomic-embed-text"  # 768 dim - primary (local)
EMBED_BATCH_SIZE = 96
OLLAMA_URL = "http://127.0.0.1:11434/api/embed"

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
OPENAI_API_KEY = os.environ["OPENAI_API_KEY"]

SB_HEADERS_MIN = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json",
    "Prefer": "return=minimal",
}
SB_HEADERS_REPR = {**SB_HEADERS_MIN, "Prefer": "return=representation"}

openai_client = OpenAI(api_key=OPENAI_API_KEY)
enc = tiktoken.encoding_for_model("gpt-4")


# -------------------- Logging --------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[logging.StreamHandler(), logging.FileHandler(PDF_CACHE_DIR / "attachment_analyzer.log")],
)
log = logging.getLogger("attachment_analyzer")


# -------------------- Supabase REST helpers --------------------

def sb_get(table: str, select: str = "*", filters: Optional[Dict[str, str]] = None, limit: int = 1000) -> List[dict]:
    """GET all rows from a table with pagination using REST.

    filters: dict of raw PostgREST query fragments, e.g. {"status": "in.(Otvorená,Vyhlásená)"}
    """
    out: List[dict] = []
    offset = 0
    while True:
        params = {"select": select, "offset": str(offset), "limit": str(limit)}
        if filters:
            params.update(filters)
        r = requests.get(f"{SUPABASE_URL}/rest/v1/{table}", headers=SB_HEADERS_MIN, params=params)
        r.raise_for_status()
        batch = r.json()
        out.extend(batch)
        if len(batch) < limit:
            break
        offset += limit
    return out


def sb_insert(table: str, rows: List[dict], dry_run: bool = False) -> None:
    if not rows:
        return
    if dry_run:
        log.info(f"[dry-run] Would insert {len(rows)} rows into {table}")
        return

    url = f"{SUPABASE_URL}/rest/v1/{table}"
    for i in range(0, len(rows), 500):
        batch = rows[i : i + 500]
        r = requests.post(url, headers=SB_HEADERS_MIN, json=batch, timeout=60)
        if r.status_code >= 400:
            log.error(f"Insert error {r.status_code}: {r.text[:300]}")
            r.raise_for_status()


def sb_exists_v2_chunk(call_id: str, source_url: str) -> bool:
    params = {
        "select": "id",
        "call_id": f"eq.{call_id}",
        "source_url": f"eq.{source_url}",
        "limit": "1",
    }
    r = requests.get(f"{SUPABASE_URL}/rest/v1/v2_call_chunks", headers=SB_HEADERS_MIN, params=params, timeout=30)
    if r.status_code != 200:
        return False
    return len(r.json()) > 0


def ensure_v2_enriched_call_stub(call_id: str, title: str, dry_run: bool = False) -> None:
    """Ensure v2_enriched_calls has a row with id=call_id (FK target).

    Allowed enrichment_status values include 'pending' (validated in test).
    """
    params = {"select": "id", "id": f"eq.{call_id}", "limit": "1"}
    r = requests.get(f"{SUPABASE_URL}/rest/v1/v2_enriched_calls", headers=SB_HEADERS_MIN, params=params, timeout=30)
    r.raise_for_status()
    if r.json():
        return

    stub = {"id": call_id, "title_clean": title, "enrichment_status": "pending"}
    if dry_run:
        log.info(f"[dry-run] Would create v2_enriched_calls stub: {call_id}")
        return

    r2 = requests.post(f"{SUPABASE_URL}/rest/v1/v2_enriched_calls", headers=SB_HEADERS_MIN, json=stub, timeout=30)
    if r2.status_code >= 400:
        log.error(f"Failed to create v2_enriched_calls stub for {call_id}: {r2.text[:400]}")
        r2.raise_for_status()


# -------------------- Attachment sourcing --------------------

def _is_pdf_attachment(att: dict) -> bool:
    ft = (att.get("file_type") or att.get("type") or "").strip().lower()
    if ft == "pdf":
        return True
    url = (att.get("url") or att.get("href") or "").lower()
    return url.endswith(".pdf")


def get_call_attachments(call: dict) -> List[dict]:
    """Return attachments for a call (normalized: {name,url,file_type}).

    Sources:
    - If grant_calls_v2 has an `attachments` JSONB column (some deployments), use it.
    - For portal.itms21.sk: if JSONB column not available, fetch documents via the ITMS21 public API
      using call_url (?id=XXXX) and build API download URLs.
    - Otherwise: use grant_call_attachments related table.

    This is intentionally defensive: DB schemas differ between environments.
    """

    call_id = call["id"]
    source = (call.get("source") or "").strip()

    # 1) Try grant_calls_v2.attachments JSONB if the column exists.
    try:
        r = requests.get(
            f"{SUPABASE_URL}/rest/v1/grant_calls_v2",
            headers=SB_HEADERS_MIN,
            params={"select": "id,attachments", "id": f"eq.{call_id}", "limit": "1"},
            timeout=30,
        )
        if r.status_code == 200:
            data = r.json()
            if data:
                attachments = data[0].get("attachments")
                if isinstance(attachments, list) and len(attachments) > 0:
                    norm: List[dict] = []
                    for a in attachments:
                        if not isinstance(a, dict):
                            continue
                        url = a.get("url") or a.get("href")
                        if not url:
                            continue
                        norm.append(
                            {
                                "name": a.get("name") or a.get("title") or "attachment",
                                "url": url,
                                "file_type": a.get("file_type") or a.get("type"),
                            }
                        )
                    if norm:
                        return norm
        # If the column doesn't exist, PostgREST returns 400; just continue.
    except Exception:
        pass

    # 2) ITMS21: derive attachment URLs from the public API (most docs are PDFs but URLs have no extension).
    if source == "portal.itms21.sk":
        call_url = call.get("call_url") or ""
        m = re.search(r"[?&]id=(\d+)", call_url)
        if m:
            itms_id = m.group(1)
            api_url = f"https://api.itms21.sk/public/v1/vyzva/id/{itms_id}"
            try:
                resp = requests.get(
                    api_url,
                    timeout=30,
                    headers={"Accept": "application/json", "Origin": "https://portal.itms21.sk", "Referer": "https://portal.itms21.sk/"},
                )
                resp.raise_for_status()
                detail = resp.json()
                # Observed fields (2026-02): `dokument` is a list of {nazov, uuid}
                dokumenty = detail.get("dokument") or detail.get("dokumenty") or []
                norm: List[dict] = []
                if isinstance(dokumenty, list):
                    for doc in dokumenty:
                        if not isinstance(doc, dict):
                            continue
                        name = doc.get("nazov") or doc.get("nazovSk")
                        doc_uuid = doc.get("uuid") or doc.get("id")
                        if not doc_uuid:
                            continue
                        url = f"https://api.itms21.sk/public/v1/dokument/{doc_uuid}"
                        ft = None
                        if isinstance(name, str) and "." in name:
                            ft = name.rsplit(".", 1)[-1].lower()
                        # Keep PDFs only (others like docx/xlsx are not supported by this analyzer)
                        if ft == "pdf" or (isinstance(name, str) and name.lower().endswith(".pdf")):
                            norm.append({"name": (name or f"dokument_{doc_uuid}")[:500], "url": url, "file_type": ft})
                if norm:
                    return norm
            except Exception as e:
                log.warning(f"ITMS21 API attachments fetch failed for call_id={call_id}: {e}")

    # 3) Fallback: related table grant_call_attachments
    rows = sb_get(
        "grant_call_attachments",
        select="grant_call_id,name,url,file_type",
        filters={"grant_call_id": f"eq.{call_id}"},
        limit=1000,
    )
    return [{"name": r.get("name") or "attachment", "url": r["url"], "file_type": r.get("file_type")} for r in rows]


# -------------------- PDF download & extraction --------------------

def download_pdf(url: str) -> Optional[Path]:
    fname = hashlib.md5(url.encode("utf-8")).hexdigest() + ".pdf"
    fpath = PDF_CACHE_DIR / fname
    if fpath.exists() and fpath.stat().st_size > 0:
        return fpath

    try:
        r = requests.get(url, timeout=DOWNLOAD_TIMEOUT_S, headers={"User-Agent": "Mozilla/5.0"})
        r.raise_for_status()
        content_type = (r.headers.get("content-type") or "").lower()
        if "pdf" not in content_type and not r.content.startswith(b"%PDF-"):
            log.warning(f"Not a PDF (content-type={content_type}): {url}")
            return None
        fpath.write_bytes(r.content)
        return fpath
    except Exception as e:
        log.error(f"Download failed: {url} ({e})")
        return None


def extract_text_pdfplumber(pdf_path: Path) -> Optional[str]:
    try:
        parts: List[str] = []
        with pdfplumber.open(str(pdf_path)) as pdf:
            for page in pdf.pages:
                t = page.extract_text()
                if t:
                    parts.append(t)
        text = "\n\n".join(parts).strip()
        return text if len(text) >= 50 else None
    except Exception as e:
        log.warning(f"pdfplumber failed for {pdf_path.name}: {e}")
        return None


def extract_text_ocr(pdf_path: Path, max_pages: int = 3) -> Optional[str]:
    """OCR fallback.

    Strategy:
    1) Try pytesseract + pdf2image if installed.
    2) If not available, return None.

    Keeps it light: OCR only first max_pages pages by default.
    """
    try:
        import pytesseract  # type: ignore
        from pdf2image import convert_from_path  # type: ignore
    except Exception:
        return None

    try:
        images = convert_from_path(str(pdf_path), first_page=1, last_page=max_pages)
        texts = []
        for img in images:
            texts.append(pytesseract.image_to_string(img))
        text = "\n\n".join(texts).strip()
        return text if len(text) >= 50 else None
    except Exception as e:
        log.warning(f"OCR failed for {pdf_path.name}: {e}")
        return None


def extract_text(pdf_path: Path) -> Tuple[Optional[str], Optional[str]]:
    text = extract_text_pdfplumber(pdf_path)
    if text:
        return text, "pdf"

    ocr_text = extract_text_ocr(pdf_path)
    if ocr_text:
        return ocr_text, "pdf_ocr"

    return None, None


# -------------------- Chunking & Embeddings --------------------

def count_tokens(text: str) -> int:
    return len(enc.encode(text))


def chunk_text(text: str, target_tokens: int = CHUNK_TARGET_TOKENS, max_tokens: int = CHUNK_MAX_TOKENS) -> List[str]:
    paragraphs = [p.strip() for p in re.split(r"\n+", text) if p.strip()]
    chunks: List[str] = []
    cur: List[str] = []
    cur_t = 0

    for p in paragraphs:
        pt = count_tokens(p)

        # hard split large paragraph
        if pt > max_tokens:
            # flush current
            if cur:
                chunks.append("\n".join(cur))
                cur, cur_t = [], 0
            # naive sentence split
            sents = re.split(r"(?<=[\.\!\?])\s+", p)
            tmp: List[str] = []
            tmp_t = 0
            for s in sents:
                st = count_tokens(s)
                if tmp and tmp_t + st > max_tokens:
                    chunks.append(" ".join(tmp))
                    tmp, tmp_t = [], 0
                tmp.append(s)
                tmp_t += st
            if tmp:
                chunks.append(" ".join(tmp))
            continue

        if cur and cur_t + pt > target_tokens:
            chunks.append("\n".join(cur))
            cur, cur_t = [], 0

        cur.append(p)
        cur_t += pt

    if cur:
        chunks.append("\n".join(cur))

    # merge tiny tail chunks
    merged: List[str] = []
    for c in chunks:
        if merged and count_tokens(merged[-1]) + count_tokens(c) < CHUNK_MIN_TOKENS * 2:
            merged[-1] = merged[-1] + "\n" + c
        else:
            merged.append(c)

    return merged


_last_embed_request_ts: float = 0.0


def _throttle_embeddings(min_interval_s: float = 1.1) -> None:
    """Keep OpenAI embeddings under ~60 RPM (1 req/s) with a small safety margin."""
    global _last_embed_request_ts
    now = time.time()
    wait = (_last_embed_request_ts + min_interval_s) - now
    if wait > 0:
        time.sleep(wait)
    _last_embed_request_ts = time.time()


def embed_texts_ollama(texts: List[str]) -> List[List[float]]:
    """Get embeddings from local Ollama server."""
    try:
        resp = requests.post(
            OLLAMA_URL,
            json={"model": OLLAMA_MODEL, "input": texts},
            timeout=300
        )
        resp.raise_for_status()
        data = resp.json()
        embeddings = data.get("embeddings", [])
        if len(embeddings) != len(texts):
            log.warning(f"Ollama returned {len(embeddings)} embeddings for {len(texts)} texts")
            return []
        # Ollama returns 768-dim vectors, pad to 1536 for consistency
        padded = [emb + [0.0] * (1536 - len(emb)) if len(emb) < 1536 else emb[:1536] for emb in embeddings]
        return padded
    except Exception as e:
        log.warning(f"Ollama embedding failed: {e}")
        return []


def embed_texts_openai(texts: List[str]) -> List[List[float]]:
    """Get embeddings from OpenAI API (fallback)."""
    out: List[List[float]] = []
    for i in range(0, len(texts), EMBED_BATCH_SIZE):
        batch = texts[i : i + EMBED_BATCH_SIZE]
        for attempt in range(4):
            try:
                _throttle_embeddings()
                resp = openai_client.embeddings.create(model=EMBED_MODEL, input=batch)
                out.extend([d.embedding for d in resp.data])
                break
            except Exception as e:
                wait = min(30, 2 ** (attempt + 1))
                log.warning(f"OpenAI embedding error attempt {attempt+1}/{4}: {e} (sleep {wait}s)")
                time.sleep(wait)
                if attempt == 3:
                    out.extend([[0.0] * 1536 for _ in batch])
    return out


def embed_texts(texts: List[str]) -> List[List[float]]:
    """Get embeddings - tries Ollama first, falls back to OpenAI."""
    if not texts:
        return []

    # Try Ollama first
    ollama_embeddings = embed_texts_ollama(texts)
    if ollama_embeddings and len(ollama_embeddings) == len(texts):
        log.info(f"Using Ollama embeddings for {len(texts)} chunks")
        return ollama_embeddings

    # Fall back to OpenAI
    log.info(f"Falling back to OpenAI embeddings for {len(texts)} chunks")
    return embed_texts_openai(texts)


# -------------------- Processing --------------------

@dataclass
class Stats:
    calls_total: int = 0
    calls_processed: int = 0
    calls_skipped: int = 0
    calls_failed: int = 0
    pdfs_ok: int = 0
    pdfs_failed: int = 0
    chunks_created: int = 0


def process_one_pdf(call_id: str, pdf_url: str, pdf_name: str, dry_run: bool = False) -> Tuple[List[dict], str, Optional[Path]]:
    """Returns (rows, status, pdf_path). pdf_path is set when a file was downloaded and can be cleaned up after DB insert."""
    if sb_exists_v2_chunk(call_id, pdf_url):
        return [], "skipped", None

    pdf_path = download_pdf(pdf_url)
    if not pdf_path:
        return [], "download_failed", None

    text, source_type = extract_text(pdf_path)
    if not text or not source_type:
        _cleanup_pdf(pdf_path)
        return [], "extraction_failed", None

    chunks = chunk_text(text)
    if not chunks:
        _cleanup_pdf(pdf_path)
        return [], "no_chunks", None

    embeddings = embed_texts(chunks) if not dry_run else [[0.0] * 1536 for _ in chunks]

    rows: List[dict] = []
    for idx, (ch, emb) in enumerate(zip(chunks, embeddings)):
        rows.append(
            {
                "call_id": call_id,
                "source_type": source_type,
                "source_url": pdf_url,
                "chunk_index": idx,
                "chunk_text": ch,
                "token_count": count_tokens(ch),
                "embedding": json.dumps(emb),
            }
        )

    # Return pdf_path so caller can delete after successful DB insert
    return rows, "ok", pdf_path


def _cleanup_pdf(pdf_path: Optional[Path]) -> None:
    """Delete a downloaded PDF to free disk space."""
    if pdf_path and pdf_path.exists():
        try:
            pdf_path.unlink()
            log.debug(f"Cleaned up PDF: {pdf_path.name}")
        except Exception as e:
            log.warning(f"Failed to cleanup PDF {pdf_path}: {e}")


def _load_state(state_path: Path) -> dict:
    if not state_path.exists():
        return {}
    try:
        return json.loads(state_path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_state(state_path: Path, state: dict) -> None:
    tmp = state_path.with_suffix(state_path.suffix + ".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(state_path)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--batch-size", type=int, default=10, help="Max 10 (rate limiting)")
    ap.add_argument("--max-calls", type=int, default=0, help="0 = no limit")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument(
        "--only-status",
        default="",
        help="Comma-separated statuses to process (default: empty = all statuses)",
    )
    ap.add_argument(
        "--allow-nonactive-statuses",
        action="store_true",
        default=True,
        help="Allow processing statuses other than Otvorená/Plánovaná (default: True).",
    )
    ap.add_argument(
        "--only-source",
        default="",
        help="Optional source filter (e.g. portal.itms21.sk). Empty = all sources.",
    )
    ap.add_argument("--resume", action="store_true", help="Resume from last processed call in state file")
    ap.add_argument(
        "--state-file",
        default=str(PDF_CACHE_DIR / "attachment_analyzer_state.json"),
        help="Path to resume/progress state JSON",
    )
    args = ap.parse_args()

    batch_size = max(1, min(10, args.batch_size))
    statuses = [s.strip() for s in args.only_status.split(",") if s.strip()]

    # If no statuses specified, process all calls
    if not statuses and not args.only_status:
        log.info("No status filter specified - processing ALL calls regardless of status")

    log.info("=== Attachment analyzer starting ===")
    log.info(f"PDF cache: {PDF_CACHE_DIR}")
    log.info(f"Dry-run: {args.dry_run}")

    state_path = Path(args.state_file)
    state = _load_state(state_path) if args.resume else {}
    resume_after_id = state.get("last_call_id") if args.resume else None

    # Fetch active calls; include deadline_at for prioritization.
    # Note: attachments presence is checked per-call because some sources store PDFs in grant_call_attachments.
    def _pg_quote(v: str) -> str:
        return '"' + v.replace('"', '\\"') + '"'

    if statuses:
        status_in = ",".join([_pg_quote(s) for s in statuses])
        calls = sb_get(
            "grant_calls_v2",
            select="id,title,source,call_url,status,deadline_at",
            filters={"status": f"in.({status_in})"},
            limit=1000,
        )
    else:
        # Fetch all calls regardless of status
        calls = sb_get(
            "grant_calls_v2",
            select="id,title,source,call_url,status,deadline_at",
            limit=1000,
        )

    if args.only_source:
        calls = [c for c in calls if (c.get("source") or "") == args.only_source]
        log.info(f"Source filter enabled: {args.only_source} | calls={len(calls)}")

    # Prioritize nearest deadlines first; NULL deadlines last.
    def _deadline_key(c: dict) -> tuple:
        d = c.get("deadline_at")
        return (0, d) if d else (1, "9999-12-31")

    calls.sort(key=_deadline_key)

    # Build list of calls that actually have PDF attachments.
    # Optimization: if --max-calls is set, stop scanning once enough candidates are found.
    call_candidates: List[dict] = []
    scan_limit = args.max_calls if args.max_calls and args.max_calls > 0 else None

    # Bulk prefetch attachments from grant_call_attachments for performance.
    # NOTE: ITMS21 attachments are often not stored in the related table; they may require JSONB/API.
    call_ids_table = [c["id"] for c in calls if (c.get("source") or "") != "portal.itms21.sk"]
    att_map: Dict[str, List[dict]] = {cid: [] for cid in call_ids_table}

    for i in range(0, len(call_ids_table), 50):
        chunk_ids = call_ids_table[i : i + 50]
        in_list = ",".join([_pg_quote(x) for x in chunk_ids])
        try:
            rows = sb_get(
                "grant_call_attachments",
                select="grant_call_id,name,url,file_type",
                filters={"grant_call_id": f"in.({in_list})"},
                limit=1000,
            )
            for r in rows:
                cid = r.get("grant_call_id")
                if cid:
                    att_map.setdefault(cid, []).append(
                        {"name": r.get("name") or "attachment", "url": r.get("url"), "file_type": r.get("file_type")}
                    )
        except Exception:
            log.exception("Bulk fetch grant_call_attachments failed; falling back to per-call fetch")
            att_map = {}
            break

    for c in calls:
        cid = c["id"]
        src = (c.get("source") or "")

        # ITMS21: do NOT pre-scan attachments here (would require 166+ API calls up-front).
        # We'll resolve attachments lazily during processing.
        if src == "portal.itms21.sk":
            call_candidates.append({**c, "pdf_attachments": []})
            if scan_limit and len(call_candidates) >= scan_limit:
                break
            continue

        # Other sources: use prefetched table attachments when available; otherwise resolve per-call.
        atts = att_map.get(cid) if att_map and cid in att_map else None
        if atts is None:
            atts = get_call_attachments(c)

        pdfs = [a for a in atts if _is_pdf_attachment(a)]
        if not pdfs:
            continue
        call_candidates.append({**c, "pdf_attachments": pdfs})
        if scan_limit and len(call_candidates) >= scan_limit:
            break

    stats = Stats(calls_total=len(call_candidates))
    log.info(f"Active calls with PDF attachments: {stats.calls_total}")

    if args.resume and resume_after_id:
        # Skip until we pass the last_call_id (inclusive). If not found, do not skip anything.
        before = len(call_candidates)
        skipping = True
        filtered: List[dict] = []
        found = False
        for c in call_candidates:
            if skipping:
                if c["id"] == resume_after_id:
                    found = True
                    skipping = False
                continue
            filtered.append(c)
        if found:
            call_candidates = filtered
            log.info(
                f"Resume enabled: last_call_id={resume_after_id} | remaining={len(call_candidates)} (from {before})"
            )
        else:
            log.warning(f"Resume state last_call_id not found in current candidate list: {resume_after_id}")

    for batch_start in range(0, len(call_candidates), batch_size):
        batch = call_candidates[batch_start : batch_start + batch_size]
        batch_num = batch_start // batch_size + 1
        log.info(f"\n--- Batch {batch_num}: calls {batch_start+1}-{min(batch_start+batch_size, len(call_candidates))}/{len(call_candidates)} ---")

        rows_to_insert: List[dict] = []
        batch_pdfs_to_cleanup: List[Path] = []

        for c in batch:
            cid = c["id"]
            title = (c.get("title") or "").strip() or cid
            status = c.get("status") or ""
            pdfs = c["pdf_attachments"]
            if (c.get("source") or "") == "portal.itms21.sk" and not pdfs:
                # Lazy resolve ITMS21 PDFs via API/JSONB
                atts = get_call_attachments(c)
                pdfs = [a for a in atts if _is_pdf_attachment(a)]
                c["pdf_attachments"] = pdfs

            if not pdfs:
                stats.calls_skipped += 1
                log.info(f"Call: {title[:80]} [{status}] PDFs=0 (skipped)")
                continue

            try:
                ensure_v2_enriched_call_stub(cid, title, dry_run=args.dry_run)
            except Exception:
                stats.calls_failed += 1
                log.exception(f"Failed to ensure v2_enriched_calls stub for call {cid}")
                continue

            log.info(f"Call: {title[:80]} [{status}] PDFs={len(pdfs)}")

            call_had_success = False
            for att in pdfs:
                url = att.get("url")
                if not url:
                    continue
                name = att.get("name") or "pdf"

                try:
                    rows, result, pdf_path = process_one_pdf(cid, url, name, dry_run=args.dry_run)
                    if result == "ok":
                        rows_to_insert.extend(rows)
                        stats.pdfs_ok += 1
                        stats.chunks_created += len(rows)
                        call_had_success = True
                        if pdf_path:
                            batch_pdfs_to_cleanup.append(pdf_path)
                    elif result == "skipped":
                        call_had_success = True
                    else:
                        stats.pdfs_failed += 1
                        log.warning(f"  PDF failed ({result}): {name[:60]} | {url[:120]}")
                except Exception:
                    stats.pdfs_failed += 1
                    log.exception(f"  PDF exception: {name[:60]} | {url[:120]}")

            if call_had_success:
                stats.calls_processed += 1
            else:
                stats.calls_failed += 1

            # Progress ping every 10 calls (requested).
            done_calls = stats.calls_processed + stats.calls_skipped + stats.calls_failed
            if done_calls % 10 == 0:
                log.info(
                    "Progress(10): "
                    + json.dumps(
                        {
                            "done_calls": done_calls,
                            "calls_total": stats.calls_total,
                            "calls_processed": stats.calls_processed,
                            "calls_skipped": stats.calls_skipped,
                            "calls_failed": stats.calls_failed,
                            "pdfs_ok": stats.pdfs_ok,
                            "pdfs_failed": stats.pdfs_failed,
                            "chunks_created": stats.chunks_created,
                        },
                        ensure_ascii=False,
                    )
                )

            # Persist resume/progress after every call (safe to resume after crash).
            if not args.dry_run:
                state.update(
                    {
                        "last_call_id": cid,
                        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                        "stats": {
                            "calls_total": stats.calls_total,
                            "calls_processed": stats.calls_processed,
                            "calls_skipped": stats.calls_skipped,
                            "calls_failed": stats.calls_failed,
                            "pdfs_ok": stats.pdfs_ok,
                            "pdfs_failed": stats.pdfs_failed,
                            "chunks_created": stats.chunks_created,
                        },
                    }
                )
                try:
                    _save_state(state_path, state)
                except Exception:
                    log.exception(f"Failed to save state to {state_path}")

        if rows_to_insert:
            log.info(f"Inserting chunks: {len(rows_to_insert)}")
            try:
                sb_insert("v2_call_chunks", rows_to_insert, dry_run=args.dry_run)
                log.info("Insert OK")
                # Clean up PDFs only after successful DB insert
                for pdf_p in batch_pdfs_to_cleanup:
                    _cleanup_pdf(pdf_p)
                if batch_pdfs_to_cleanup:
                    log.info(f"Cleaned up {len(batch_pdfs_to_cleanup)} PDF files")
                batch_pdfs_to_cleanup.clear()
            except Exception:
                log.exception("Batch insert failed — keeping PDFs for retry")

        log.info(
            "Progress: "
            + json.dumps(
                {
                    "calls_total": stats.calls_total,
                    "calls_processed": stats.calls_processed,
                    "calls_skipped": stats.calls_skipped,
                    "calls_failed": stats.calls_failed,
                    "pdfs_ok": stats.pdfs_ok,
                    "pdfs_failed": stats.pdfs_failed,
                    "chunks_created": stats.chunks_created,
                },
                ensure_ascii=False,
            )
        )

    log.info("\n=== FINAL REPORT ===")
    log.info(
        json.dumps(
            {
                "calls_total": stats.calls_total,
                "calls_processed": stats.calls_processed,
                "calls_skipped": stats.calls_skipped,
                "calls_failed": stats.calls_failed,
                "pdfs_ok": stats.pdfs_ok,
                "pdfs_failed": stats.pdfs_failed,
                "chunks_created": stats.chunks_created,
            },
            ensure_ascii=False,
            indent=2,
        )
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

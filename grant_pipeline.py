#!/usr/bin/env python3
"""grant_pipeline.py - Unified grant attachment pipeline.

Combines:
- document_classifier.py  (regex classification)
- ai_classifier.py        (GPT-4o-mini classification for uncertain cases)
- attachment_analyzer.py   (PDF download, text extraction, chunking)
- vectorize_calls_v3.py    (ZIP handling, OpenAI embeddings)

Into a single resumable pipeline that downloads attachments (PDF/ZIP),
classifies documents, extracts text, chunks, embeds via OpenAI
text-embedding-3-small, and stores into v2_call_chunks.

Usage:
    python3 v2/grant_pipeline.py                           # process all
    python3 v2/grant_pipeline.py --dry-run                 # simulate only
    python3 v2/grant_pipeline.py --max-calls 5             # limit calls
    python3 v2/grant_pipeline.py --source portal.itms21.sk # ITMS21 only
    python3 v2/grant_pipeline.py --fresh                   # ignore state
    python3 v2/grant_pipeline.py --skip-classification     # embed everything
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import logging
import os
import re
import sys
import time
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pdfplumber
import requests
import tiktoken
from dotenv import load_dotenv
from openai import OpenAI

# ---------------------------------------------------------------------------
# Environment
# ---------------------------------------------------------------------------
load_dotenv(Path(__file__).resolve().parents[1] / ".env")

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
OPENAI_API_KEY = os.environ["OPENAI_API_KEY"]

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
PIPELINE_DIR = Path("/tmp/grant_pipeline")
PIPELINE_DIR.mkdir(parents=True, exist_ok=True)

STATE_FILE = PIPELINE_DIR / "state.json"
LOG_FILE = PIPELINE_DIR / "pipeline.log"
PDF_CACHE_DIR = PIPELINE_DIR / "pdfs"
PDF_CACHE_DIR.mkdir(parents=True, exist_ok=True)

DOWNLOAD_TIMEOUT_S = 120
MAX_FILE_SIZE_MB = 50

CHUNK_TARGET_TOKENS = 400
CHUNK_MAX_TOKENS = 512
CHUNK_MIN_TOKENS = 100
CHUNK_OVERLAP_TOKENS = 50  # ~10-12% overlap

EMBED_MODEL = "text-embedding-3-large"  # 3072 dim
EMBED_BATCH_SIZE = 64  # smaller batches for larger model

# Pricing (USD per 1M tokens, as of 2026-03)
EMBED_PRICE_PER_1M = 0.13  # text-embedding-3-large pricing
CLASSIFIER_INPUT_PRICE = 0.15
CLASSIFIER_OUTPUT_PRICE = 0.60

# ---------------------------------------------------------------------------
# Clients
# ---------------------------------------------------------------------------
SB_HEADERS = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json",
    "Prefer": "return=minimal",
}

openai_client = OpenAI(api_key=OPENAI_API_KEY)
enc = tiktoken.encoding_for_model("gpt-4")

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
    ],
)
log = logging.getLogger("grant_pipeline")
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("openai").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)


# ===========================================================================
# Stats
# ===========================================================================
@dataclass
class PipelineStats:
    calls_processed: int = 0
    calls_skipped: int = 0
    calls_failed: int = 0
    calls_no_attachments: int = 0
    pdfs_downloaded: int = 0
    pdfs_classified_key: int = 0
    pdfs_classified_skip: int = 0
    pdfs_failed: int = 0
    chunks_created: int = 0
    ai_classifier_calls: int = 0
    embed_tokens: int = 0
    classifier_input_tokens: int = 0
    classifier_output_tokens: int = 0
    zips_extracted: int = 0

    def to_dict(self) -> dict:
        return {k: v for k, v in self.__dict__.items()}

    def estimated_cost(self) -> dict:
        embed_cost = (self.embed_tokens / 1_000_000) * EMBED_PRICE_PER_1M
        ci_cost = (self.classifier_input_tokens / 1_000_000) * CLASSIFIER_INPUT_PRICE
        co_cost = (self.classifier_output_tokens / 1_000_000) * CLASSIFIER_OUTPUT_PRICE
        return {
            "embedding_cost_usd": round(embed_cost, 6),
            "classifier_cost_usd": round(ci_cost + co_cost, 6),
            "total_cost_usd": round(embed_cost + ci_cost + co_cost, 6),
        }


# ===========================================================================
# Supabase REST helpers
# ===========================================================================
def sb_get(
    table: str, select: str = "*",
    filters: Optional[Dict[str, str]] = None, limit: int = 1000,
) -> List[dict]:
    out: List[dict] = []
    offset = 0
    while True:
        params = {"select": select, "offset": str(offset), "limit": str(limit)}
        if filters:
            params.update(filters)
        r = requests.get(
            f"{SUPABASE_URL}/rest/v1/{table}",
            headers=SB_HEADERS, params=params, timeout=60,
        )
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
        batch = rows[i:i + 500]
        r = requests.post(url, headers=SB_HEADERS, json=batch, timeout=60)
        if r.status_code >= 400:
            log.error(f"Insert error {r.status_code}: {r.text[:300]}")
            r.raise_for_status()


def sb_chunk_exists(call_id: int, source: str) -> bool:
    """Check if chunks already exist for call_id + source."""
    params = {
        "select": "id",
        "call_id": f"eq.{call_id}",
        "source": f"eq.{source}",
        "limit": "1",
    }
    try:
        r = requests.get(
            f"{SUPABASE_URL}/rest/v1/v2_call_chunks",
            headers=SB_HEADERS, params=params, timeout=30,
        )
        return r.status_code == 200 and len(r.json()) > 0
    except Exception:
        return False


# ===========================================================================
# Document Classification (regex + AI)
# ===========================================================================
SKIP_PATTERNS = [
    r'formular', r'ziadost', r'formul[áa]r', r'žiadost', r'application',
    r'vyplnenie', r'vzor',
    r'pouzivatelsky[_-]?manual', r'manual[_-]?pouzivatela', r'user[_-]?manual',
    r'portal', r'navod[_-]?na[_-]?pouzitie',
    r'informacie[_-]?gdpr', r'gdpr[_-]?inform', r'osobne[_-]?udaje',
    r'test[_-]?podniku', r'podnik[_-]?v[_-]?tazkostiach', r'dnsh',
    r'priloha[_-]?c\._?1[_-]?formular', r'priloha[_-]?1[_-]?formular',
]

KEY_PATTERNS = [
    r'vyzva', r'prirucka[_-]?pre[_-]?ziadatela', r'priručk[aa].*žiada',
    r'podmienky', r'crit[ée]ria', r'hodnotiace[_-]?kriteria',
    r'zoznam[_-]?opravnenych', r'opravneni[_-]?ziadatelia',
    r'specifikacia', r'v[ýy]zva.*program', r'usmernenie', r'metodika',
]


@dataclass
class Classification:
    category: str   # key, form, technical, unknown
    confidence: float
    reason: str
    should_embed: bool


def classify_by_filename(filename: str) -> Optional[Classification]:
    fn = filename.lower()
    for pat in SKIP_PATTERNS:
        if re.search(pat, fn):
            cat = "form" if ("form" in pat or "ziad" in pat) else "technical"
            return Classification(cat, 0.85, f"Filename matches skip: {pat}", False)
    for pat in KEY_PATTERNS:
        if re.search(pat, fn):
            return Classification("key", 0.80, f"Filename matches key: {pat}", True)
    return None


def classify_with_ai(text: str, filename: str, stats: PipelineStats) -> Optional[Classification]:
    preview = text[:2500]
    prompt = (
        f"Analyze this document and classify it.\n\n"
        f"Filename: {filename}\n\nDocument text (first part):\n---\n{preview}\n---\n\n"
        f"Categories:\n"
        f"1. KEY - Grant conditions, criteria, eligible costs, call description, evaluation methodology, guide for applicants. EMBED.\n"
        f"2. FORM - Application forms, templates to fill out, submission checklists. Do NOT embed.\n"
        f"3. TECHNICAL - User manuals, GDPR, technical specs, portal instructions. Do NOT embed.\n"
        f"4. UNKNOWN - Cannot determine. Do NOT embed.\n\n"
        f'Respond ONLY in JSON:\n'
        f'{{"category": "key|form|technical|unknown", "confidence": 0.0-1.0, "reasoning": "brief", "should_embed": true|false}}\n\n'
        f"Return only JSON."
    )
    try:
        input_tok = len(enc.encode(prompt)) + 30
        stats.classifier_input_tokens += input_tok

        resp = requests.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {OPENAI_API_KEY}", "Content-Type": "application/json"},
            json={
                "model": "gpt-4o-mini",
                "messages": [
                    {"role": "system", "content": "You are a document classifier for grant management. Be concise."},
                    {"role": "user", "content": prompt},
                ],
                "temperature": 0.1,
                "max_tokens": 150,
                "response_format": {"type": "json_object"},
            },
            timeout=15,
        )
        resp.raise_for_status()
        result = resp.json()
        content = result["choices"][0]["message"]["content"]
        out_tok = result.get("usage", {}).get("completion_tokens", 100)
        stats.classifier_output_tokens += out_tok
        stats.ai_classifier_calls += 1

        data = json.loads(content)
        return Classification(
            category=data.get("category", "unknown").lower(),
            confidence=data.get("confidence", 0.5),
            reason=f"AI: {data.get('reasoning', 'no reason')}",
            should_embed=data.get("should_embed", False),
        )
    except Exception as e:
        log.warning(f"AI classification failed for {filename}: {e}")
        return None


def classify_document(
    filename: str, text: Optional[str],
    stats: PipelineStats, skip_classification: bool = False,
) -> Classification:
    if skip_classification:
        return Classification("key", 1.0, "skip-classification flag", True)

    fn_result = classify_by_filename(filename)
    if fn_result:
        if fn_result.category in ("form", "technical") and fn_result.confidence > 0.7:
            return fn_result
        if fn_result.category == "key" and fn_result.confidence > 0.7:
            return fn_result

    # AI for uncertain / unknown
    if text and len(text) > 200:
        ai_result = classify_with_ai(text, filename, stats)
        if ai_result:
            return ai_result

    if fn_result:
        return fn_result

    return Classification("unknown", 0.5, "No classification possible, default embed", True)


# ===========================================================================
# Download & ZIP extraction
# ===========================================================================
def _cache_path(url: str) -> Path:
    return PDF_CACHE_DIR / (hashlib.md5(url.encode("utf-8")).hexdigest() + ".pdf")


def download_content(url: str) -> Tuple[Optional[bytes], Optional[str]]:
    try:
        r = requests.get(url, timeout=DOWNLOAD_TIMEOUT_S, headers={"User-Agent": "Mozilla/5.0"}, stream=True)
        r.raise_for_status()
        ct = (r.headers.get("content-type") or "").lower()
        cl = int(r.headers.get("content-length", 0))
        if cl > MAX_FILE_SIZE_MB * 1024 * 1024:
            log.warning(f"Skip too large ({cl / 1024 / 1024:.1f}MB): {url}")
            return None, None
        content = b""
        for chunk in r.iter_content(chunk_size=65536):
            content += chunk
            if len(content) > MAX_FILE_SIZE_MB * 1024 * 1024:
                log.warning(f"Download exceeded {MAX_FILE_SIZE_MB}MB: {url}")
                return None, None
        return content, ct
    except Exception as e:
        log.warning(f"Download failed {url}: {e}")
        return None, None


def extract_pdfs_from_content(
    content: bytes, content_type: str, url: str,
) -> List[Tuple[Path, str]]:
    """Returns (pdf_path, source_label). ZIP source = url#inner.pdf"""
    results: List[Tuple[Path, str]] = []
    if content is None:
        return results

    is_pdf = "pdf" in content_type or content[:5] == b"%PDF-"
    is_zip = "zip" in content_type or content[:2] == b"PK"

    if is_pdf:
        path = _cache_path(url)
        if not path.exists():
            path.write_bytes(content)
        results.append((path, url))
        return results

    if is_zip:
        try:
            with zipfile.ZipFile(io.BytesIO(content)) as zf:
                for name in zf.namelist():
                    if not name.lower().endswith(".pdf"):
                        continue
                    if name.startswith("__MACOSX"):
                        continue
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

    # Unknown type - try as PDF by magic bytes
    if content[:5] == b"%PDF-":
        path = _cache_path(url)
        if not path.exists():
            path.write_bytes(content)
        results.append((path, url))

    return results


# ===========================================================================
# Text extraction
# ===========================================================================
def extract_text_pdfplumber(pdf_path: Path) -> Optional[str]:
    try:
        parts: List[str] = []
        with pdfplumber.open(str(pdf_path)) as pdf:
            for page in pdf.pages[:100]:
                t = page.extract_text()
                if t:
                    parts.append(t)
        text = "\n\n".join(parts).strip()
        return text if len(text) >= 50 else None
    except Exception as e:
        log.warning(f"pdfplumber failed {pdf_path.name}: {e}")
        return None


def extract_text_ocr(pdf_path: Path, max_pages: int = 3) -> Optional[str]:
    try:
        import pytesseract
        from pdf2image import convert_from_path
    except ImportError:
        return None
    try:
        images = convert_from_path(str(pdf_path), first_page=1, last_page=max_pages)
        texts = [pytesseract.image_to_string(img) for img in images]
        text = "\n\n".join(texts).strip()
        return text if len(text) >= 50 else None
    except Exception as e:
        log.warning(f"OCR failed {pdf_path.name}: {e}")
        return None


def extract_text(pdf_path: Path) -> Optional[str]:
    text = extract_text_pdfplumber(pdf_path)
    if text:
        return text
    return extract_text_ocr(pdf_path)


# ===========================================================================
# Chunking
# ===========================================================================
def count_tokens(text: str) -> int:
    return len(enc.encode(text))


_SECTION_RE = re.compile(
    r"^(?:"
    r"\d+[\.\)]\s+[A-ZÁČĎÉÍĽŇÓŠŤÚÝŽ]"  # "1. Oprávnení žiadatelia"
    r"|[A-Z][A-ZÁČĎÉÍĽŇÓŠŤÚÝŽ\s]{5,60}$"  # "OPRÁVNENÉ VÝDAVKY"
    r"|Príloha\s"
    r"|Podmienka\s"
    r")",
    re.MULTILINE,
)


def _detect_sections(text: str) -> List[str]:
    """Extract section headings from text."""
    headings = []
    for line in text.split("\n"):
        line = line.strip()
        if not line or len(line) > 120:
            continue
        if _SECTION_RE.match(line):
            headings.append(line)
    return headings


def chunk_text(text: str, doc_context: str = "") -> List[str]:
    """Chunk text into pieces of ~CHUNK_TARGET_TOKENS.
    
    doc_context: prefix added to each chunk for embedding context
    (e.g. "Výzva: Výstavba kanalizácie | Dokument: Príloha 4 oprávnené výdavky")
    """
    paragraphs = [p.strip() for p in re.split(r"\n+", text) if p.strip()]
    chunks: List[str] = []
    cur: List[str] = []
    cur_t = 0
    current_section = ""

    for p in paragraphs:
        # Track section headings
        if _SECTION_RE.match(p) and len(p) <= 120:
            current_section = p.strip()

        pt = count_tokens(p)
        if pt > CHUNK_MAX_TOKENS:
            if cur:
                chunks.append(("\n".join(cur), current_section))
                cur, cur_t = [], 0
            sents = re.split(r"(?<=[\.\!\?])\s+", p)
            tmp: List[str] = []
            tmp_t = 0
            for s in sents:
                st = count_tokens(s)
                if tmp and tmp_t + st > CHUNK_MAX_TOKENS:
                    chunks.append((" ".join(tmp), current_section))
                    tmp, tmp_t = [], 0
                tmp.append(s)
                tmp_t += st
            if tmp:
                chunks.append((" ".join(tmp), current_section))
            continue
        if cur and cur_t + pt > CHUNK_TARGET_TOKENS:
            chunks.append(("\n".join(cur), current_section))
            cur, cur_t = [], 0
        cur.append(p)
        cur_t += pt

    if cur:
        chunks.append(("\n".join(cur), current_section))

    # Merge tiny chunks
    merged: List[tuple] = []
    for c_text, c_section in chunks:
        if merged and count_tokens(merged[-1][0]) + count_tokens(c_text) < CHUNK_MIN_TOKENS * 2:
            merged[-1] = (merged[-1][0] + "\n" + c_text, merged[-1][1] or c_section)
        else:
            merged.append((c_text, c_section))

    # Add overlap between chunks (carry last N tokens from previous chunk)
    if CHUNK_OVERLAP_TOKENS > 0 and len(merged) > 1:
        overlapped: List[tuple] = [merged[0]]
        for i in range(1, len(merged)):
            prev_text = merged[i - 1][0]
            prev_lines = prev_text.split("\n")
            # Take last lines up to overlap token budget
            overlap_lines: List[str] = []
            overlap_t = 0
            for line in reversed(prev_lines):
                lt = count_tokens(line)
                if overlap_t + lt > CHUNK_OVERLAP_TOKENS:
                    break
                overlap_lines.insert(0, line)
                overlap_t += lt
            if overlap_lines:
                overlap_prefix = "\n".join(overlap_lines)
                new_text = overlap_prefix + "\n" + merged[i][0]
                overlapped.append((new_text, merged[i][1]))
            else:
                overlapped.append(merged[i])
        merged = overlapped

    # Add context prefix to each chunk
    result: List[str] = []
    for c_text, c_section in merged:
        prefix_parts = []
        if doc_context:
            prefix_parts.append(doc_context)
        if c_section:
            prefix_parts.append(f"Sekcia: {c_section}")
        if prefix_parts:
            prefix = " | ".join(prefix_parts)
            result.append(f"[{prefix}]\n{c_text}")
        else:
            result.append(c_text)
    return result


# ===========================================================================
# Embeddings - OpenAI only
# ===========================================================================
_last_embed_ts: float = 0.0


def _throttle_embed() -> None:
    global _last_embed_ts
    now = time.time()
    wait = (_last_embed_ts + 1.0) - now
    if wait > 0:
        time.sleep(wait)
    _last_embed_ts = time.time()


def embed_texts(
    texts: List[str], dry_run: bool = False,
) -> Tuple[List[List[float]], int]:
    """Returns (embeddings, total_tokens)."""
    if not texts:
        return [], 0
    if dry_run:
        return [[0.0] * 1536 for _ in texts], 0

    out: List[List[float]] = []
    total_tokens = 0
    for i in range(0, len(texts), EMBED_BATCH_SIZE):
        batch = texts[i:i + EMBED_BATCH_SIZE]
        for attempt in range(5):
            try:
                _throttle_embed()
                resp = openai_client.embeddings.create(model=EMBED_MODEL, input=batch)
                out.extend([d.embedding for d in resp.data])
                total_tokens += resp.usage.total_tokens
                break
            except Exception as e:
                wait = min(60, 2 ** (attempt + 1))
                log.warning(f"Embed error attempt {attempt + 1}/5: {e} (sleep {wait}s)")
                time.sleep(wait)
                if attempt == 4:
                    log.error(f"Embedding failed after 5 attempts, batch at index {i}")
                    out.extend([[0.0] * 1536 for _ in batch])
    return out, total_tokens


# ===========================================================================
# Attachment resolution
# ===========================================================================
def get_itms21_attachments(call_url: str) -> List[dict]:
    m = re.search(r"[?&]id=(\d+)", call_url or "")
    if not m:
        return []
    itms_id = m.group(1)
    try:
        r = requests.get(
            f"https://api.itms21.sk/public/v1/vyzva/id/{itms_id}",
            timeout=30, headers={"Accept": "application/json"},
        )
        r.raise_for_status()
        data = r.json()
        docs = data.get("dokument") or data.get("dokumenty") or []
        result: List[dict] = []
        for d in docs:
            if not isinstance(d, dict):
                continue
            uuid = d.get("uuid") or d.get("id")
            if not uuid:
                continue
            name = d.get("nazov") or d.get("nazovSk") or f"dokument_{uuid}"
            url = f"https://api.itms21.sk/public/v1/dokument/{uuid}"
            result.append({"name": name, "url": url})
        return result
    except Exception as e:
        log.warning(f"ITMS21 API failed for {call_url}: {e}")
        return []


def get_attachments_for_call(call: dict) -> List[dict]:
    source = call.get("source", "")
    call_id = call["id"]

    if source == "portal.itms21.sk":
        return get_itms21_attachments(call.get("call_url", ""))

    # JSONB attachments column
    try:
        r = requests.get(
            f"{SUPABASE_URL}/rest/v1/grant_calls_v2",
            headers=SB_HEADERS,
            params={"select": "attachments", "id": f"eq.{call_id}", "limit": "1"},
            timeout=30,
        )
        if r.status_code == 200 and r.json():
            atts = r.json()[0].get("attachments")
            if isinstance(atts, list) and atts:
                norm = []
                for a in atts:
                    if not isinstance(a, dict):
                        continue
                    url = a.get("url") or a.get("href")
                    if url:
                        norm.append({"name": a.get("name") or "attachment", "url": url})
                if norm:
                    return norm
    except Exception:
        pass

    # Fallback: grant_call_attachments table
    rows = sb_get(
        "grant_call_attachments", select="name,url,file_type",
        filters={"grant_call_id": f"eq.{call_id}"}, limit=100,
    )
    return [{"name": r.get("name", "att"), "url": r["url"]} for r in rows if r.get("url")]


# ===========================================================================
# State management
# ===========================================================================
def load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"processed_ids": [], "stats": {}}


def save_state(state: dict) -> None:
    tmp = STATE_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(STATE_FILE)


# ===========================================================================
# Process a single PDF
# ===========================================================================
def process_pdf(
    call_id: int, pdf_path: Path, source_label: str, filename: str,
    stats: PipelineStats, dry_run: bool = False, skip_classification: bool = False,
    call_title: str = "",
) -> List[dict]:
    """Process one PDF. Returns rows for v2_call_chunks insert.
    
    DB columns: call_id, content, embedding, chunk_index, source
    """
    if sb_chunk_exists(call_id, source_label):
        log.debug(f"    Already exists: call_id={call_id} source={source_label[:60]}")
        return []

    text = extract_text(pdf_path)
    if not text:
        log.warning(f"    No text: {filename}")
        stats.pdfs_failed += 1
        return []

    classification = classify_document(filename, text, stats, skip_classification)
    if not classification.should_embed:
        log.info(
            f"    SKIP {filename[:60]}: {classification.category} "
            f"({classification.confidence:.2f}) - {classification.reason}"
        )
        stats.pdfs_classified_skip += 1
        return []

    stats.pdfs_classified_key += 1
    log.info(
        f"    EMBED {filename[:60]}: {classification.category} "
        f"({classification.confidence:.2f})"
    )

    # Build document context for chunk prefix
    doc_name = Path(filename).stem[:80]
    doc_context = f"Výzva: {call_title[:100]}" if call_title else ""
    if doc_name:
        doc_context += f" | Dokument: {doc_name}" if doc_context else f"Dokument: {doc_name}"

    chunks = chunk_text(text, doc_context=doc_context)
    if not chunks:
        log.warning(f"    No chunks: {filename}")
        stats.pdfs_failed += 1
        return []

    embeddings, embed_tokens = embed_texts(chunks, dry_run=dry_run)
    stats.embed_tokens += embed_tokens

    rows: List[dict] = []
    for idx, (ch, emb) in enumerate(zip(chunks, embeddings)):
        rows.append({
            "call_id": call_id,
            "content": ch,
            "embedding": json.dumps(emb),
            "chunk_index": idx,
            "source": source_label,
        })

    stats.chunks_created += len(rows)
    return rows


# ===========================================================================
# Process a single call
# ===========================================================================
SKIP_EXTS = (
    '.docx', '.doc', '.xlsx', '.xls', '.pptx', '.ppt',
    '.jpg', '.jpeg', '.png', '.gif', '.csv', '.xml', '.html',
)


def process_call(
    call: dict, stats: PipelineStats,
    dry_run: bool = False, skip_classification: bool = False,
) -> bool:
    """Process one grant call. Returns True on success."""
    call_id = call["id"]
    title = (call.get("title") or "")[:80]
    source = call.get("source", "")

    attachments = get_attachments_for_call(call)
    if not attachments:
        stats.calls_no_attachments += 1
        log.info(f"  No attachments: {title}")
        return True

    log.info(f"  Call {call_id}: {title} | source={source} | attachments={len(attachments)}")

    all_rows: List[dict] = []
    any_pdf_ok = False

    for ai_idx, att in enumerate(attachments):
        url = att.get("url", "")
        if not url:
            continue
        name = att.get("name", "attachment")
        name_lower = name.lower()

        if any(name_lower.endswith(ext) for ext in SKIP_EXTS):
            log.debug(f"    [{ai_idx + 1}/{len(attachments)}] Skip non-PDF: {name_lower[:60]}")
            continue

        log.info(f"    [{ai_idx + 1}/{len(attachments)}] Downloading: {name[:60]}...")
        content, ct = download_content(url)
        if content is None:
            stats.pdfs_failed += 1
            continue
        stats.pdfs_downloaded += 1
        log.info(f"    [{ai_idx + 1}] {len(content) / 1024:.0f}KB, type={ct[:30]}")

        is_zip = "zip" in (ct or "") or (content[:2] == b"PK")
        pdf_files = extract_pdfs_from_content(content, ct or "", url)
        if is_zip:
            stats.zips_extracted += 1
            log.info(f"    [{ai_idx + 1}] ZIP: {len(pdf_files)} PDFs extracted")

        if not pdf_files:
            if not is_zip:
                stats.pdfs_failed += 1
            continue

        for pdf_path, source_label in pdf_files:
            pdf_filename = name
            if "#" in source_label:
                pdf_filename = source_label.split("#", 1)[1]

            rows = process_pdf(
                call_id, pdf_path, source_label, pdf_filename,
                stats, dry_run=dry_run, skip_classification=skip_classification,
                call_title=title,
            )
            if rows:
                all_rows.extend(rows)
                any_pdf_ok = True
            elif not rows and sb_chunk_exists(call_id, source_label):
                any_pdf_ok = True  # already processed before

    if all_rows:
        log.info(f"  Inserting {len(all_rows)} chunks for call {call_id}...")
        try:
            sb_insert("v2_call_chunks", all_rows, dry_run=dry_run)
            stats.calls_processed += 1
            log.info(f"  Insert OK")
        except Exception as e:
            log.error(f"  Insert failed for call {call_id}: {e}")
            stats.calls_failed += 1
            return False
    elif any_pdf_ok:
        stats.calls_processed += 1
    else:
        stats.calls_skipped += 1

    return True


# ===========================================================================
# Main
# ===========================================================================
def main() -> int:
    ap = argparse.ArgumentParser(description="Unified grant attachment pipeline")
    ap.add_argument("--dry-run", action="store_true", help="Simulate only, no DB writes or embeddings")
    ap.add_argument("--max-calls", type=int, default=0, help="Max calls to process (0 = no limit)")
    ap.add_argument("--source", default="", help="Filter by source (e.g. portal.itms21.sk)")
    ap.add_argument("--fresh", action="store_true", help="Ignore previous state, start fresh")
    ap.add_argument("--skip-classification", action="store_true", help="Skip classification, embed everything")
    ap.add_argument("--status", default="otvorená", help="Filter by status (default: otvorená, use 'all' for no filter)")
    ap.add_argument("--call-id", type=int, default=0, help="Process only this call ID")
    args = ap.parse_args()

    log.info("=" * 60)
    log.info("=== GRANT PIPELINE STARTING ===")
    log.info(f"dry-run={args.dry_run} max-calls={args.max_calls} source={args.source or 'ALL'}")
    log.info(f"fresh={args.fresh} skip-classification={args.skip_classification} status={args.status}")
    log.info("=" * 60)

    # Load state
    state = load_state() if not args.fresh else {"processed_ids": [], "stats": {}}
    done_ids = set(state.get("processed_ids", []))
    log.info(f"Previously processed: {len(done_ids)} calls")

    # Fetch calls (with status filter)
    status_filter = {}
    if args.status and args.status.lower() != "all":
        status_filter["status"] = f"eq.{args.status}"
    calls = sb_get("grant_calls_v2", select="id,title,source,call_url,status,deadline_at",
                    filters=status_filter if status_filter else None, limit=1000)
    log.info(f"Total calls in DB (status={args.status}): {len(calls)}")

    # Call ID filter
    if args.call_id:
        calls = [c for c in calls if c.get("id") == args.call_id]
        log.info(f"Call ID filter {args.call_id}: {len(calls)} calls")

    # Source filter
    if args.source:
        calls = [c for c in calls if (c.get("source") or "") == args.source]
        log.info(f"Source filter '{args.source}': {len(calls)} calls")

    # Skip already processed
    remaining = [c for c in calls if c["id"] not in done_ids]
    log.info(f"After skipping done: {len(remaining)} calls")

    # Limit
    if args.max_calls and args.max_calls > 0:
        remaining = remaining[:args.max_calls]
        log.info(f"Limited to: {len(remaining)} calls")

    stats = PipelineStats()
    start_time = time.time()

    for i, call in enumerate(remaining):
        title = (call.get("title") or "")[:80]
        source = call.get("source", "")

        try:
            process_call(call, stats, dry_run=args.dry_run, skip_classification=args.skip_classification)
        except Exception as e:
            log.error(f"[{i + 1}/{len(remaining)}] FAILED {title}: {e}")
            stats.calls_failed += 1

        # Mark as processed
        done_ids.add(call["id"])

        # Progress every 10 calls
        if (i + 1) % 10 == 0 or (i + 1) == len(remaining):
            elapsed = time.time() - start_time
            rate = (i + 1) / elapsed * 60 if elapsed > 0 else 0
            log.info(
                f"=== PROGRESS {i + 1}/{len(remaining)} ({rate:.1f} calls/min) | "
                f"processed={stats.calls_processed} skipped={stats.calls_skipped} "
                f"failed={stats.calls_failed} no_att={stats.calls_no_attachments} | "
                f"PDFs: dl={stats.pdfs_downloaded} key={stats.pdfs_classified_key} "
                f"skip={stats.pdfs_classified_skip} fail={stats.pdfs_failed} | "
                f"chunks={stats.chunks_created} ai_calls={stats.ai_classifier_calls} ==="
            )

        # Save state after each call
        state["processed_ids"] = list(done_ids)
        state["stats"] = stats.to_dict()
        state["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        try:
            save_state(state)
        except Exception:
            log.exception("Failed to save state")

    # Final report
    elapsed = time.time() - start_time
    cost = stats.estimated_cost()

    log.info("")
    log.info("=" * 60)
    log.info("=== FINAL REPORT ===")
    log.info("=" * 60)
    log.info(f"Time: {elapsed / 60:.1f} minutes")
    log.info(f"Calls processed:      {stats.calls_processed}")
    log.info(f"Calls skipped:        {stats.calls_skipped}")
    log.info(f"Calls failed:         {stats.calls_failed}")
    log.info(f"Calls no attachments: {stats.calls_no_attachments}")
    log.info(f"PDFs downloaded:      {stats.pdfs_downloaded}")
    log.info(f"PDFs classified KEY:  {stats.pdfs_classified_key}")
    log.info(f"PDFs classified SKIP: {stats.pdfs_classified_skip}")
    log.info(f"PDFs failed:          {stats.pdfs_failed}")
    log.info(f"ZIPs extracted:       {stats.zips_extracted}")
    log.info(f"Chunks created:       {stats.chunks_created}")
    log.info(f"AI classifier calls:  {stats.ai_classifier_calls}")
    log.info(f"Embed tokens:         {stats.embed_tokens}")
    log.info(f"Estimated cost:       ${cost['total_cost_usd']:.6f}")
    log.info(f"  Embedding:          ${cost['embedding_cost_usd']:.6f}")
    log.info(f"  Classifier:         ${cost['classifier_cost_usd']:.6f}")
    log.info("=" * 60)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
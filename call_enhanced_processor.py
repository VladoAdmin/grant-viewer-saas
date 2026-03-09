"""Enhanced processing for grant calls.

Features:
- Screenshot call page (Playwright)
- Extract PDF text (+ OCR fallback)
- Chunk + embed content
- Detect related calls (simple heuristic + semantic search)
"""

import json
import os
import re
import tempfile
from typing import Dict, List, Optional

import requests

from storage import SUPABASE_URL, SUPABASE_KEY

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
EMBEDDING_MODEL = "text-embedding-3-small"


# ---------------------------------------------------------------------
# Supabase helpers
# ---------------------------------------------------------------------

def _sb_headers() -> Dict[str, str]:
    if not SUPABASE_URL or not SUPABASE_KEY:
        raise RuntimeError("SUPABASE_URL/KEY missing")
    return {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "return=representation",
    }


def _sb_post(table: str, data: List[Dict]) -> List[Dict]:
    url = f"{SUPABASE_URL}/rest/v1/{table}"
    resp = requests.post(url, headers=_sb_headers(), data=json.dumps(data))
    resp.raise_for_status()
    return resp.json() if resp.text else []


def _sb_patch(table: str, filters: Dict[str, str], data: Dict) -> List[Dict]:
    url = f"{SUPABASE_URL}/rest/v1/{table}"
    params = {k: f"eq.{v}" for k, v in filters.items()}
    resp = requests.patch(url, headers=_sb_headers(), params=params, data=json.dumps(data))
    resp.raise_for_status()
    return resp.json() if resp.text else []


def _sb_get(table: str, params: Dict) -> List[Dict]:
    url = f"{SUPABASE_URL}/rest/v1/{table}"
    resp = requests.get(url, headers=_sb_headers(), params=params)
    resp.raise_for_status()
    return resp.json() if resp.text else []


# ---------------------------------------------------------------------
# Screenshot (Playwright)
# ---------------------------------------------------------------------

def take_screenshot(url: str, output_path: str) -> Optional[str]:
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(url, wait_until="networkidle", timeout=60000)
            page.set_viewport_size({"width": 1280, "height": 720})
            page.screenshot(path=output_path, full_page=True)
            browser.close()
        return output_path
    except Exception:
        return None


# ---------------------------------------------------------------------
# Text extraction
# ---------------------------------------------------------------------

def extract_text_from_pdf(path: str) -> str:
    try:
        import pdfplumber

        with pdfplumber.open(path) as pdf:
            return "\n".join([page.extract_text() or "" for page in pdf.pages])
    except Exception:
        try:
            from PyPDF2 import PdfReader

            reader = PdfReader(path)
            return "\n".join([page.extract_text() or "" for page in reader.pages])
        except Exception:
            return ""


def ocr_image(path: str) -> str:
    try:
        import pytesseract
        from PIL import Image

        return pytesseract.image_to_string(Image.open(path))
    except Exception:
        return ""


def extract_text_from_html(url: str) -> str:
    resp = requests.get(url, timeout=60)
    resp.raise_for_status()
    html = resp.text
    try:
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html, "lxml")
        for tag in soup(["script", "style", "noscript"]):
            tag.decompose()
        return "\n".join([t.strip() for t in soup.get_text("\n").splitlines() if t.strip()])
    except Exception:
        return re.sub(r"\s+", " ", html)


# ---------------------------------------------------------------------
# Chunking + embeddings
# ---------------------------------------------------------------------

def chunk_text(text: str, min_chars: int = 800, max_chars: int = 2000) -> List[str]:
    paragraphs = [p.strip() for p in text.split("\n") if p.strip()]
    chunks: List[str] = []
    buf: List[str] = []
    buf_len = 0

    for p in paragraphs:
        if buf_len + len(p) + 1 > max_chars and buf:
            chunks.append("\n".join(buf))
            buf = []
            buf_len = 0
        buf.append(p)
        buf_len += len(p) + 1
        if buf_len >= min_chars:
            chunks.append("\n".join(buf))
            buf = []
            buf_len = 0

    if buf:
        chunks.append("\n".join(buf))

    return chunks


def embed_texts(texts: List[str]) -> List[List[float]]:
    if not OPENAI_API_KEY:
        raise RuntimeError("OPENAI_API_KEY missing for embeddings")

    resp = requests.post(
        "https://api.openai.com/v1/embeddings",
        headers={
            "Authorization": f"Bearer {OPENAI_API_KEY}",
            "Content-Type": "application/json",
        },
        json={"model": EMBEDDING_MODEL, "input": texts},
        timeout=60,
    )
    resp.raise_for_status()
    data = resp.json()
    return [item["embedding"] for item in data.get("data", [])]


# ---------------------------------------------------------------------
# Related calls (simple heuristic)
# ---------------------------------------------------------------------

def detect_related_calls(title: str, limit: int = 5) -> List[str]:
    """Find related calls by title similarity (simple ilike query)."""
    if not title:
        return []
    keyword = re.sub(r"\W+", " ", title).strip().split(" ")[:4]
    if not keyword:
        return []
    term = "%" + "%".join(keyword) + "%"
    rows = _sb_get(
        "v2_enriched_calls",
        {
            "select": "id,title_clean",
            "title_clean": f"ilike.{term}",
            "limit": str(limit),
        },
    )
    return [r["id"] for r in rows if r.get("id")]


# ---------------------------------------------------------------------
# Main processor
# ---------------------------------------------------------------------

def process_call(
    call_id: str,
    call_url: str,
    attachment_urls: Optional[List[str]] = None,
) -> Dict:
    """Process a call: screenshot, extract HTML/PDFs, chunk + embed, update DB."""
    attachment_urls = attachment_urls or []

    # 1) Screenshot
    screenshot_path = None
    screenshot_url = None
    screenshot_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "output", "screenshots")
    os.makedirs(screenshot_dir, exist_ok=True)
    screenshot_path = os.path.join(screenshot_dir, f"{call_id}.png")
    screenshot = take_screenshot(call_url, screenshot_path)
    screenshot_url = screenshot if screenshot else None

    with tempfile.TemporaryDirectory() as tmpdir:
        # 2) HTML extraction
        html_text = extract_text_from_html(call_url)
        html_chunks = chunk_text(html_text)

        # 3) PDF extraction
        pdf_chunks: List[str] = []
        for url in attachment_urls:
            try:
                pdf_path = os.path.join(tmpdir, os.path.basename(url.split("?")[0]))
                resp = requests.get(url, timeout=60)
                resp.raise_for_status()
                with open(pdf_path, "wb") as f:
                    f.write(resp.content)
                pdf_text = extract_text_from_pdf(pdf_path)
                if not pdf_text.strip() and pdf_path.lower().endswith(('.png', '.jpg', '.jpeg')):
                    pdf_text = ocr_image(pdf_path)
                if pdf_text.strip():
                    pdf_chunks.extend(chunk_text(pdf_text))
            except Exception:
                continue

    # 4) Embeddings + store chunks
    chunk_rows = []
    for source_type, chunks in ("html", html_chunks), ("pdf", pdf_chunks):
        if not chunks:
            continue
        embeddings = embed_texts(chunks)
        for idx, (chunk, emb) in enumerate(zip(chunks, embeddings)):
            chunk_rows.append(
                {
                    "call_id": call_id,
                    "source_type": source_type,
                    "source_url": call_url,
                    "chunk_index": idx,
                    "chunk_text": chunk,
                    "token_count": len(chunk.split()),
                    "embedding": emb,
                }
            )

    if chunk_rows:
        _sb_post("v2_call_chunks", chunk_rows)

    # 5) Related calls heuristic
    title_rows = _sb_get(
        "v2_enriched_calls",
        {"select": "title_clean", "id": f"eq.{call_id}"},
    )
    title_hint = title_rows[0].get("title_clean") if title_rows else None
    related_ids = detect_related_calls(title_hint or html_text[:200])

    # 6) Update enriched_calls
    update = {
        "screenshot_url": screenshot_url,
        "summary_text": html_text[:2000] if html_text else None,
        "conditions_text": None,
        "related_calls_ids": related_ids or None,
    }
    _sb_patch("v2_enriched_calls", {"id": call_id}, update)

    return {
        "call_id": call_id,
        "chunks_saved": len(chunk_rows),
        "screenshot": screenshot_url,
        "related_calls": related_ids,
    }


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Enhanced call processor")
    parser.add_argument("--call-id", required=True)
    parser.add_argument("--url", required=True)
    parser.add_argument("--attachment", action="append", default=[])
    args = parser.parse_args()

    result = process_call(args.call_id, args.url, args.attachment)
    print(json.dumps(result, indent=2))

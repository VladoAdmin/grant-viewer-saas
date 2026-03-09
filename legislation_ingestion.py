"""Legislation ingestion utilities for GrantBot.

- Downloads legislation documents
- Extracts and chunks text
- Generates embeddings (OpenAI text-embedding-3-small)
- Stores metadata + chunks in Supabase
"""

import hashlib
import json
import os
import re
import tempfile
from typing import Dict, Iterable, List, Optional, Tuple

import requests

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

from storage import SUPABASE_URL, SUPABASE_KEY

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
EMBEDDING_MODEL = "text-embedding-3-small"
EMBEDDING_DIM = 1536


# ---------------------------------------------------------------------
# Helpers: Supabase
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


def _sb_post(table: str, data: List[Dict], on_conflict: Optional[str] = None) -> List[Dict]:
    url = f"{SUPABASE_URL}/rest/v1/{table}"
    headers = _sb_headers()
    params = {}
    if on_conflict:
        headers["Prefer"] = "resolution=merge-duplicates,return=representation"
        params["on_conflict"] = on_conflict
    resp = requests.post(url, headers=headers, params=params, data=json.dumps(data))
    resp.raise_for_status()
    return resp.json() if resp.text else []


# ---------------------------------------------------------------------
# Helpers: download + extract
# ---------------------------------------------------------------------

def download_file(url: str, dest_dir: str) -> str:
    resp = requests.get(url, timeout=60, allow_redirects=True)
    resp.raise_for_status()
    fname = url.split("/")[-1].split("?")[0] or "document"
    path = os.path.join(dest_dir, fname)
    with open(path, "wb") as f:
        f.write(resp.content)
    return path


def _file_hash(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def extract_text_from_pdf(path: str) -> str:
    try:
        import pdfplumber

        text_parts = []
        with pdfplumber.open(path) as pdf:
            for page in pdf.pages:
                text_parts.append(page.extract_text() or "")
        return "\n".join(text_parts)
    except Exception:
        try:
            from PyPDF2 import PdfReader

            reader = PdfReader(path)
            text = []
            for page in reader.pages:
                text.append(page.extract_text() or "")
            return "\n".join(text)
        except Exception as e:
            raise RuntimeError(f"PDF extraction failed: {e}")


def extract_text_from_html(path_or_url: str, html: Optional[str] = None) -> str:
    if html is None:
        if path_or_url.startswith("http"):
            resp = requests.get(path_or_url, timeout=60)
            resp.raise_for_status()
            html = resp.text
        else:
            with open(path_or_url, "r", encoding="utf-8", errors="ignore") as f:
                html = f.read()
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


def embed_texts(texts: Iterable[str]) -> List[List[float]]:
    if not OPENAI_API_KEY:
        raise RuntimeError("OPENAI_API_KEY missing for embeddings")

    embeddings: List[List[float]] = []
    batch: List[str] = []

    def flush() -> None:
        if not batch:
            return
        resp = requests.post(
            "https://api.openai.com/v1/embeddings",
            headers={
                "Authorization": f"Bearer {OPENAI_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": EMBEDDING_MODEL,
                "input": batch,
            },
            timeout=60,
        )
        resp.raise_for_status()
        data = resp.json()
        for item in data.get("data", []):
            embeddings.append(item["embedding"])
        batch.clear()

    for t in texts:
        batch.append(t)
        if len(batch) >= 64:
            flush()
    flush()
    return embeddings


# ---------------------------------------------------------------------
# Main ingestion
# ---------------------------------------------------------------------

def ingest_legislation_document(
    title: str,
    source_url: str,
    doc_type: str = "regulation",
    jurisdiction: str = "EU",
    published_at: Optional[str] = None,
    effective_from: Optional[str] = None,
    effective_to: Optional[str] = None,
    metadata: Optional[Dict] = None,
) -> Dict:
    """Download a legislation document, chunk and store it in Supabase.

    Returns a dict with document_id and chunk_count.
    """
    metadata = metadata or {}

    with tempfile.TemporaryDirectory() as tmpdir:
        path = download_file(source_url, tmpdir)
        content_hash = _file_hash(path)
        file_type = "pdf" if path.lower().endswith(".pdf") else "html"

        if file_type == "pdf":
            text = extract_text_from_pdf(path)
        else:
            text = extract_text_from_html(path)

    if not text.strip():
        raise RuntimeError("No text extracted from document")

    # Upsert document
    doc_rows = _sb_post(
        "legislation_documents",
        [
            {
                "title": title,
                "doc_type": doc_type,
                "jurisdiction": jurisdiction,
                "published_at": published_at,
                "effective_from": effective_from,
                "effective_to": effective_to,
                "source_url": source_url,
                "metadata": metadata,
            }
        ],
        on_conflict="source_url",
    )
    document_id = doc_rows[0]["id"] if doc_rows else None

    # Insert file
    file_rows = _sb_post(
        "legislation_files",
        [
            {
                "document_id": document_id,
                "file_url": source_url,
                "file_type": file_type,
                "file_format": "application/pdf" if file_type == "pdf" else "text/html",
                "content_hash": content_hash,
                "downloaded_at": "now()",
            }
        ],
        on_conflict="document_id,file_url",
    )
    file_id = file_rows[0]["id"] if file_rows else None

    # Chunk + embeddings
    chunks = chunk_text(text)
    embeddings = embed_texts(chunks)

    chunk_rows = []
    for idx, (chunk, emb) in enumerate(zip(chunks, embeddings)):
        chunk_rows.append(
            {
                "document_id": document_id,
                "file_id": file_id,
                "chunk_index": idx,
                "chunk_text": chunk,
                "token_count": len(chunk.split()),
                "embedding": emb,
            }
        )

    if chunk_rows:
        _sb_post("legislation_chunks", chunk_rows)

    return {"document_id": document_id, "chunk_count": len(chunk_rows)}


if __name__ == "__main__":
    # Simple CLI for manual testing
    import argparse

    parser = argparse.ArgumentParser(description="Ingest a legislation document")
    parser.add_argument("--title", required=True)
    parser.add_argument("--url", required=True)
    parser.add_argument("--doc-type", default="regulation")
    parser.add_argument("--jurisdiction", default="EU")
    args = parser.parse_args()

    result = ingest_legislation_document(
        title=args.title,
        source_url=args.url,
        doc_type=args.doc_type,
        jurisdiction=args.jurisdiction,
    )
    print(json.dumps(result, indent=2))

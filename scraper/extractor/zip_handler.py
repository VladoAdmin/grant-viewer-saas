"""ZIP archive handling and content extraction.

Reuses patterns from universal_extractor.py and vectorize_calls_v3.py.
Handles: direct PDF, ZIP containing PDFs, DOCX files.
"""

import hashlib
import io
import logging
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple

import requests

from ..config import MAX_FILE_SIZE_MB, REQUEST_TIMEOUT, STORAGE_PATH
from .pdf_extractor import extract_text_from_bytes, extract_text_from_docx

log = logging.getLogger(__name__)

CACHE_DIR = Path(STORAGE_PATH) / "pdf_cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)


@dataclass
class ExtractedDocument:
    """A document extracted from a URL (PDF, ZIP, or DOCX)."""
    filename: str
    source_url: str
    text: str
    pages: int = 0
    file_type: str = "pdf"


def _cache_path(url: str) -> Path:
    """Generate cache path for a URL."""
    return CACHE_DIR / (hashlib.md5(url.encode()).hexdigest() + ".bin")


def download_content(url: str, timeout: int = REQUEST_TIMEOUT,
                     max_mb: int = MAX_FILE_SIZE_MB) -> Tuple[Optional[bytes], Optional[str]]:
    """Download URL content. Returns (bytes, content_type) or (None, None) on failure."""
    try:
        r = requests.get(url, timeout=timeout,
                         headers={"User-Agent": "Mozilla/5.0"}, stream=True)
        r.raise_for_status()
        ct = (r.headers.get("content-type") or "").lower()
        cl = int(r.headers.get("content-length", 0))

        if cl > max_mb * 1024 * 1024:
            log.warning(f"File too large ({cl / 1024 / 1024:.1f}MB): {url}")
            return None, None

        content = b""
        for chunk in r.iter_content(chunk_size=65536):
            content += chunk
            if len(content) > max_mb * 1024 * 1024:
                log.warning(f"Download exceeded {max_mb}MB: {url}")
                return None, None

        return content, ct
    except Exception as e:
        log.warning(f"Download failed {url}: {e}")
        return None, None


def _extract_pdfs_from_zip(content: bytes, base_url: str) -> List[Tuple[bytes, str, str]]:
    """Extract PDF bytes from ZIP. Returns list of (pdf_bytes, filename, source_label)."""
    results = []
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as zf:
            for name in zf.namelist():
                if name.startswith("__MACOSX"):
                    continue
                name_lower = name.lower()
                if name_lower.endswith(".pdf"):
                    pdf_bytes = zf.read(name)
                    if len(pdf_bytes) >= 100:
                        results.append((pdf_bytes, name, f"{base_url}#{name}"))
                elif name_lower.endswith((".docx", ".doc")):
                    docx_bytes = zf.read(name)
                    if len(docx_bytes) >= 100:
                        results.append((docx_bytes, name, f"{base_url}#{name}"))
    except Exception as e:
        log.warning(f"ZIP extraction failed: {e}")
    return results


def extract_from_url(url: str) -> List[ExtractedDocument]:
    """Download and extract documents from a URL.

    Handles: direct PDF, ZIP with PDFs, DOCX files.
    Returns list of ExtractedDocument with text content.
    """
    # Check cache first
    cached = _cache_path(url)
    if cached.exists():
        content = cached.read_bytes()
        ct = "application/pdf" if content[:5] == b"%PDF-" else "application/octet-stream"
    else:
        content, ct = download_content(url)
        if content is None:
            return []
        # Cache the download
        try:
            cached.write_bytes(content)
        except Exception:
            pass

    results: List[ExtractedDocument] = []
    ct = ct or ""

    # Direct PDF
    if "pdf" in ct or content[:5] == b"%PDF-":
        text = extract_text_from_bytes(content)
        if text:
            fname = url.rsplit("/", 1)[-1] if "/" in url else "document.pdf"
            results.append(ExtractedDocument(
                filename=fname, source_url=url, text=text, file_type="pdf"
            ))
        return results

    # ZIP file
    if "zip" in ct or content[:2] == b"PK":
        # First check if it's a DOCX (DOCX is also PK/ZIP)
        if url.lower().endswith((".docx", ".doc")) or b"word/document.xml" in content[:10000]:
            text = extract_text_from_docx(content)
            if text:
                fname = url.rsplit("/", 1)[-1] if "/" in url else "document.docx"
                results.append(ExtractedDocument(
                    filename=fname, source_url=url, text=text, file_type="docx"
                ))
            return results

        # It's a real ZIP — extract PDFs from inside
        for pdf_bytes, name, source_label in _extract_pdfs_from_zip(content, url):
            if name.lower().endswith((".docx", ".doc")):
                text = extract_text_from_docx(pdf_bytes)
            else:
                text = extract_text_from_bytes(pdf_bytes)
            if text:
                results.append(ExtractedDocument(
                    filename=name, source_url=source_label, text=text,
                    file_type="docx" if name.lower().endswith(".docx") else "pdf"
                ))
        return results

    # Unknown — try as PDF anyway
    if content[:5] == b"%PDF-":
        text = extract_text_from_bytes(content)
        if text:
            results.append(ExtractedDocument(
                filename="document.pdf", source_url=url, text=text, file_type="pdf"
            ))

    return results


def extract_from_path(path: str) -> List[ExtractedDocument]:
    """Extract documents from a local file path."""
    p = Path(path)
    if not p.exists():
        return []

    content = p.read_bytes()
    if p.suffix.lower() == ".pdf" or content[:5] == b"%PDF-":
        text = extract_text_from_bytes(content)
        if text:
            return [ExtractedDocument(filename=p.name, source_url=str(p), text=text, file_type="pdf")]
    elif p.suffix.lower() in (".zip",):
        results = []
        for pdf_bytes, name, source_label in _extract_pdfs_from_zip(content, str(p)):
            text = extract_text_from_bytes(pdf_bytes)
            if text:
                results.append(ExtractedDocument(
                    filename=name, source_url=source_label, text=text, file_type="pdf"
                ))
        return results
    elif p.suffix.lower() in (".docx",):
        text = extract_text_from_docx(content)
        if text:
            return [ExtractedDocument(filename=p.name, source_url=str(p), text=text, file_type="docx")]

    return []

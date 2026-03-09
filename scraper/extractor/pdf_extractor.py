"""PDF and DOCX text extraction.

Reuses patterns from universal_extractor.py and vectorize_calls_v3.py.
Uses PyMuPDF (fitz) for PDF extraction, python-docx for DOCX.
"""

import io
import logging
import threading
from pathlib import Path
from typing import Optional

from ..config import MAX_PDF_PAGES

log = logging.getLogger(__name__)


def extract_text_from_bytes(content: bytes, max_pages: int = MAX_PDF_PAGES) -> Optional[str]:
    """Extract text from PDF bytes using PyMuPDF (fitz).

    Uses a thread with timeout to prevent hanging on corrupt PDFs.
    """
    result = [None]

    def _extract():
        try:
            import fitz
            doc = fitz.open(stream=content, filetype="pdf")
            parts = []
            for i in range(min(max_pages, len(doc))):
                text = doc[i].get_text()
                if text:
                    parts.append(text)
            doc.close()
            text = "\n\n".join(parts).strip()
            result[0] = text if len(text) >= 50 else None
        except Exception as e:
            log.warning(f"PDF extraction failed: {e}")

    t = threading.Thread(target=_extract)
    t.start()
    t.join(timeout=60)
    if t.is_alive():
        log.warning("PDF extraction timed out after 60s")
        return None
    return result[0]


def extract_text_from_pdf(pdf_path: str, max_pages: int = MAX_PDF_PAGES) -> Optional[str]:
    """Extract text from a PDF file path."""
    try:
        content = Path(pdf_path).read_bytes()
        return extract_text_from_bytes(content, max_pages)
    except Exception as e:
        log.warning(f"Failed to read PDF {pdf_path}: {e}")
        return None


def extract_text_from_docx(content: bytes) -> Optional[str]:
    """Extract text from DOCX bytes."""
    try:
        import docx
        doc = docx.Document(io.BytesIO(content))
        text = "\n".join(p.text for p in doc.paragraphs if p.text.strip())
        return text if len(text) >= 50 else None
    except ImportError:
        log.warning("python-docx not installed, skipping DOCX extraction")
        return None
    except Exception as e:
        log.warning(f"DOCX extraction failed: {e}")
        return None

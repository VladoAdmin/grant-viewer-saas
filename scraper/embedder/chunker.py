"""Text chunking for grant documents.

Reuses patterns from smart_chunker_v2.py and vectorize_calls_v3.py.
Splits text into semantic chunks with context prefixes.
"""

import logging
import re
from dataclasses import dataclass
from typing import List, Optional

import tiktoken

from ..config import CHUNK_MAX_TOKENS, CHUNK_MIN_TOKENS, CHUNK_TARGET_TOKENS

log = logging.getLogger(__name__)

# Tokenizer
_enc = None


def _get_encoder():
    global _enc
    if _enc is None:
        _enc = tiktoken.encoding_for_model("gpt-4")
    return _enc


def count_tokens(text: str) -> int:
    """Count tokens in text."""
    return len(_get_encoder().encode(text))


@dataclass
class Chunk:
    """A text chunk ready for embedding."""
    text: str           # Full text including context prefix
    raw_text: str       # Raw text without prefix
    chunk_index: int
    doc_name: str
    doc_type: str
    call_title: str
    token_count: int
    section_heading: Optional[str] = None


def _split_into_paragraphs(text: str) -> List[str]:
    """Split text into paragraphs."""
    return [p.strip() for p in re.split(r"\n\n+", text) if p.strip()]


def _split_into_sentences(text: str) -> List[str]:
    """Split text into sentences."""
    return [s.strip() for s in re.split(r"(?<=[\.\!\?])\s+", text) if s.strip()]


def chunk_text(text: str, target: int = CHUNK_TARGET_TOKENS,
               max_tokens: int = CHUNK_MAX_TOKENS,
               min_tokens: int = CHUNK_MIN_TOKENS) -> List[str]:
    """Chunk text into token-bounded pieces.

    Strategy: split by paragraphs, then sentences as fallback.
    No overlap for simplicity (context prefix provides enough context).
    """
    paragraphs = _split_into_paragraphs(text)
    chunks: List[str] = []
    current: List[str] = []
    current_tokens = 0

    for para in paragraphs:
        pt = count_tokens(para)

        # If a single paragraph exceeds max, split by sentences
        if pt > max_tokens:
            # Flush current buffer
            if current:
                chunks.append("\n\n".join(current))
                current, current_tokens = [], 0

            sentences = _split_into_sentences(para)
            sent_buf: List[str] = []
            sent_tokens = 0
            for sent in sentences:
                st = count_tokens(sent)
                if sent_buf and sent_tokens + st > max_tokens:
                    chunks.append(" ".join(sent_buf))
                    sent_buf, sent_tokens = [], 0
                sent_buf.append(sent)
                sent_tokens += st
            if sent_buf:
                chunks.append(" ".join(sent_buf))
            continue

        # If adding this paragraph would exceed target, flush
        if current and current_tokens + pt > target:
            chunks.append("\n\n".join(current))
            current, current_tokens = [], 0

        current.append(para)
        current_tokens += pt

    if current:
        chunks.append("\n\n".join(current))

    # Merge tiny chunks
    merged: List[str] = []
    for c in chunks:
        if merged and count_tokens(merged[-1]) + count_tokens(c) < min_tokens * 2:
            merged[-1] += "\n\n" + c
        else:
            merged.append(c)

    return merged


def chunk_document(text: str, call_title: str, doc_name: str,
                   doc_type: str = "main") -> List[Chunk]:
    """Chunk a document with context prefixes.

    Each chunk gets a prefix:
        [Výzva: {call_title} | Dokument: {doc_name} | Typ: {doc_type}]
        {chunk_text}
    """
    raw_chunks = chunk_text(text)

    result: List[Chunk] = []
    for i, raw in enumerate(raw_chunks):
        # Context prefix
        prefix = f"[Výzva: {call_title[:100]} | Dokument: {doc_name[:80]} | Typ: {doc_type}]"
        full_text = f"{prefix}\n{raw}"

        result.append(Chunk(
            text=full_text,
            raw_text=raw,
            chunk_index=i,
            doc_name=doc_name,
            doc_type=doc_type,
            call_title=call_title,
            token_count=count_tokens(full_text),
        ))

    return result

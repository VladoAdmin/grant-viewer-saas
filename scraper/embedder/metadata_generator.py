"""Chunk metadata generator using GPT-4o-mini.

Generates structured metadata for each chunk:
- section_title: section the chunk belongs to
- summary: 1-2 sentence summary
- content_tags: relevant keywords
- info_density: summary|detail|mixed
"""

import json
import logging
import time
from typing import Dict, List, Optional

from openai import OpenAI

from ..config import OPENAI_API_KEY

log = logging.getLogger(__name__)

METADATA_MODEL = "gpt-4o-mini"
METADATA_BATCH_SIZE = 10
MAX_RETRIES = 3

_oai: Optional[OpenAI] = None


def _get_openai() -> OpenAI:
    global _oai
    if _oai is None:
        _oai = OpenAI(api_key=OPENAI_API_KEY, timeout=60.0)
    return _oai


METADATA_SYSTEM_PROMPT = """Si analytik grantových dokumentov. Pre každý textový chunk vygeneruj metadáta.

Vráť JSON pole s objektami pre KAŽDÝ chunk v rovnakom poradí:
[
  {
    "chunk_index": 0,
    "section_title": "Názov sekcie alebo témy (max 60 znakov)",
    "summary": "1-2 vetné zhrnutie hlavného obsahu (max 150 znakov)",
    "content_tags": ["tag1", "tag2", "tag3"],
    "info_density": "summary|detail|mixed"
  }
]

Pravidlá:
- section_title: identifikuj logickú sekciu dokumentu (napr. "Oprávnené výdavky", "Podmienky poskytnutia príspevku")
- summary: stručne popíš ČO sa v časti hovorí, nie kopíruj text
- content_tags: 3-6 kľúčových slov relevantných pre vyhľadávanie (slovensky)
- info_density: "summary" ak je to prehľad/zoznam, "detail" ak ide do hĺbky, "mixed" ak oboje

Vždy vráť PLATNÝ JSON. Žiadny markdown, žiadne vysvetlenia."""


def generate_chunk_metadata(
    chunk_content: str,
    doc_type: str,
    call_title: str,
) -> Dict:
    """Generate metadata for a single chunk.

    Returns dict with keys: section_title, summary, content_tags, info_density
    """
    result = generate_batch_metadata(
        chunks=[{"content": chunk_content, "index": 0}],
        doc_type=doc_type,
        call_title=call_title,
    )
    return result[0] if result else _default_metadata()


def generate_batch_metadata(
    chunks: List[Dict],
    doc_type: str,
    call_title: str,
) -> List[Dict]:
    """Generate metadata for a batch of chunks.

    Args:
        chunks: list of {"content": str, "index": int}
        doc_type: document type (main, conditions, criteria, etc.)
        call_title: grant call title for context

    Returns:
        List of metadata dicts in the same order as input chunks
    """
    if not chunks:
        return []

    results: List[Dict] = []

    # Process in batches of METADATA_BATCH_SIZE
    for batch_start in range(0, len(chunks), METADATA_BATCH_SIZE):
        batch = chunks[batch_start:batch_start + METADATA_BATCH_SIZE]
        batch_results = _process_batch(batch, doc_type, call_title)
        results.extend(batch_results)

    return results


def _process_batch(
    batch: List[Dict],
    doc_type: str,
    call_title: str,
) -> List[Dict]:
    """Process a single batch of chunks through GPT-4o-mini."""
    oai = _get_openai()

    # Build user prompt with numbered chunks
    chunk_texts = []
    for i, chunk in enumerate(batch):
        content = chunk["content"]
        # Truncate very long chunks for metadata extraction
        if len(content) > 2000:
            content = content[:2000] + "..."
        chunk_texts.append(f"--- Chunk {i} ---\n{content}")

    user_prompt = (
        f"Výzva: {call_title}\n"
        f"Typ dokumentu: {doc_type}\n"
        f"Počet chunkov: {len(batch)}\n\n"
        + "\n\n".join(chunk_texts)
    )

    for attempt in range(MAX_RETRIES):
        try:
            resp = oai.chat.completions.create(
                model=METADATA_MODEL,
                messages=[
                    {"role": "system", "content": METADATA_SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.1,
                max_tokens=2000,
                response_format={"type": "json_object"},
            )

            raw = resp.choices[0].message.content or "[]"
            parsed = json.loads(raw)

            # Handle both direct array and wrapped object
            if isinstance(parsed, dict):
                # Try common wrapper keys
                for key in ("chunks", "metadata", "results", "data"):
                    if key in parsed:
                        parsed = parsed[key]
                        break
                else:
                    # Single chunk result wrapped in object
                    if "section_title" in parsed:
                        parsed = [parsed]
                    else:
                        # Try to find any list value
                        for v in parsed.values():
                            if isinstance(v, list):
                                parsed = v
                                break

            if not isinstance(parsed, list):
                log.warning(f"Metadata response not a list, attempt {attempt + 1}")
                if attempt < MAX_RETRIES - 1:
                    time.sleep(1)
                    continue
                return [_default_metadata() for _ in batch]

            # Validate and normalize each item
            result = []
            for i in range(len(batch)):
                if i < len(parsed):
                    meta = _validate_metadata(parsed[i])
                else:
                    meta = _default_metadata()
                result.append(meta)

            return result

        except json.JSONDecodeError as e:
            log.warning(f"Metadata JSON parse error (attempt {attempt + 1}): {e}")
            if attempt < MAX_RETRIES - 1:
                time.sleep(1)
        except Exception as e:
            wait = min(30, 2 ** (attempt + 1))
            log.warning(f"Metadata generation error (attempt {attempt + 1}/{MAX_RETRIES}): {e}")
            if attempt < MAX_RETRIES - 1:
                time.sleep(wait)

    log.error(f"Metadata generation failed after {MAX_RETRIES} attempts, using defaults")
    return [_default_metadata() for _ in batch]


def _validate_metadata(meta: Dict) -> Dict:
    """Validate and normalize a metadata dict."""
    return {
        "section_title": str(meta.get("section_title", ""))[:100],
        "summary": str(meta.get("summary", ""))[:200],
        "content_tags": _validate_tags(meta.get("content_tags", [])),
        "info_density": meta.get("info_density", "mixed")
        if meta.get("info_density") in ("summary", "detail", "mixed")
        else "mixed",
    }


def _validate_tags(tags) -> List[str]:
    """Validate content tags — must be a list of strings."""
    if not isinstance(tags, list):
        return []
    return [str(t)[:50] for t in tags if isinstance(t, (str, int, float))][:8]


def _default_metadata() -> Dict:
    """Return default metadata when generation fails."""
    return {
        "section_title": "",
        "summary": "",
        "content_tags": [],
        "info_density": "mixed",
    }


def build_enriched_prefix(
    call_title: str,
    doc_name: str,
    doc_type: str,
    metadata: Dict,
) -> str:
    """Build enriched prefix for embedding.

    Format: [Výzva: X | Dokument: Y | Typ: Z | Sekcia: A | Tags: B | Summary: C]
    """
    parts = [
        f"Výzva: {call_title[:100]}",
        f"Dokument: {doc_name[:80]}",
        f"Typ: {doc_type}",
    ]

    section = metadata.get("section_title", "")
    if section:
        parts.append(f"Sekcia: {section}")

    tags = metadata.get("content_tags", [])
    if tags:
        parts.append(f"Tags: {', '.join(tags[:6])}")

    summary = metadata.get("summary", "")
    if summary:
        parts.append(f"Zhrnutie: {summary}")

    return "[" + " | ".join(parts) + "]"

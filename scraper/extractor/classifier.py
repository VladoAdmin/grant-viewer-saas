"""Rule-based document classifier.

Classifies documents into categories based on filename and content keywords.
Reuses classification rules from PRD Appendix B and universal_extractor.py.

Enhanced for ZIP archives with UUID filenames where filename-based
classification is ineffective — relies more heavily on content analysis.
"""

import logging
import re
from dataclasses import dataclass
from typing import Optional, Tuple

log = logging.getLogger(__name__)

# Classification rules: doc_type -> (filename_keywords, content_keywords)
CLASSIFICATION_RULES = {
    "main": {
        "filename_keywords": [
            "vyzva", "výzva", "specifikacia", "špecifikácia",
            "vseobecne-podmienky", "všeobecné podmienky", "usmernenie",
            "plne-znenie", "plné znenie",
        ],
        "content_keywords": [
            "výzva", "vyzva", "špecifikácia", "specifikacia",
            "všeobecné podmienky", "usmernenie", "cieľ výzvy",
            "oprávnené aktivity", "alokácia", "deadline",
            "kód výzvy", "dátum vyhlásenia", "oprávnení žiadatelia",
            "indikatívna výška", "finančné prostriedky",
            "predmet výzvy", "účel výzvy", "výzva na predkladanie",
            "oprávnené územie", "Program Slovensko",
        ],
        "content_sections": [
            "predmet výzvy", "cieľ výzvy", "oprávnení žiadatelia",
            "oprávnené aktivity", "oprávnené územie",
            "indikatívna výška finančných prostriedkov",
            "forma a výška príspevku",
        ],
        "filename_negative": ["priloha", "príloha", "formular", "formulár", "vzor"],
        "min_pages": 5,
        "priority": 1,
    },
    "conditions": {
        "filename_keywords": [
            "podmienky", "prirucka", "príručka", "opravnen",
            "priloha-c-1", "príloha č. 1", "priloha_1",
            "synergick",
        ],
        "content_keywords": [
            "podmienky", "podmienka", "oprávnenosť", "oprávnený žiadateľ",
            "príručka", "prirucka", "synergické účinky",
            "podmienky poskytnutia príspevku",
            "podmienky oprávnenosti", "poskytnutie príspevku",
            "žiadosť o nenávratný finančný príspevok",
            "oprávnené výdavky", "neoprávnené výdavky",
            "podmienky týkajúce sa", "preukázanie splnenia",
        ],
        "content_sections": [
            "podmienky poskytnutia príspevku",
            "podmienky oprávnenosti",
            "oprávnenosť žiadateľa",
        ],
        "filename_negative": [],
        "min_pages": 2,
        "priority": 2,
    },
    "criteria": {
        "filename_keywords": [
            "kriteria", "kritériá", "hodnotenie", "vyhodnotenie",
            "priloha-c-2", "príloha č. 2", "priloha_2",
        ],
        "content_keywords": [
            "kritériá", "hodnotenie", "vyhodnotenie", "bodové hodnotenie",
            "hodnotiace kritériá", "hodnotiacie kritériá",
            "kritérium", "bodový systém", "výberové kritériá",
            "merateľný ukazovateľ", "merateľné ukazovatele",
        ],
        "content_sections": [
            "hodnotiace kritériá", "výberové kritériá",
            "kritériá pre výber projektov",
        ],
        "filename_negative": [],
        "min_pages": 2,
        "priority": 3,
    },
    "costs": {
        "filename_keywords": [
            "naklady", "náklady", "vydavky", "výdavky", "rozpocet", "rozpočet",
            "financovanie", "ciselnik", "číselník", "cennik", "cenník",
        ],
        "content_keywords": [
            "náklady", "výdavky", "rozpočet", "financovanie",
            "číselník", "cenník", "oprávnené náklady",
            "oprávnené výdavky", "neoprávnené výdavky",
            "celkové oprávnené výdavky", "jednotkové náklady",
        ],
        "content_sections": [
            "oprávnené výdavky", "neoprávnené výdavky",
        ],
        "filename_negative": [],
        "min_pages": 1,
        "priority": 4,
    },
    "skip": {
        "filename_keywords": [
            "formular", "formulár", "vzor", "gdpr", "cestne-vyhlasenie",
            "čestné vyhlásenie", "kontakty", "komisi", "manual", "manuál",
            "pouzivatelsky", "používateľský", "avizo", "ziadost",
            "kalkulac", "hospodarsk", "uzemna-prislusnost",
        ],
        "content_keywords": [],
        "content_sections": [],
        "filename_negative": [],
        "min_pages": 0,
        "priority": 0,
    },
}

# Detect UUID-like filenames where content-based classification must dominate
_UUID_RE = re.compile(r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}', re.IGNORECASE)


def _normalize(text: str) -> str:
    """Normalize text for matching (lowercase, remove diacritics-insensitive)."""
    return text.lower().strip()


def _count_keyword_hits(text: str, keywords: list) -> int:
    """Count how many keywords appear in the text."""
    text_lower = text.lower()
    return sum(1 for kw in keywords if kw.lower() in text_lower)


def _is_uninformative_filename(filename: str) -> bool:
    """Check if filename is UUID-like or otherwise uninformative."""
    fname = filename.rsplit("/", 1)[-1]  # basename
    fname_noext = fname.rsplit(".", 1)[0] if "." in fname else fname
    if _UUID_RE.match(fname_noext):
        return True
    # Also treat pure numeric or very short filenames as uninformative
    if fname_noext.replace("-", "").replace("_", "").isdigit():
        return True
    return False


def _count_section_hits(text: str, sections: list) -> int:
    """Count how many section headings appear in the text.

    Section headings are stronger signals than individual keywords because
    they indicate document structure.
    """
    text_lower = text.lower()
    return sum(1 for s in sections if s.lower() in text_lower)


def classify_document(filename: str, text: str = "", pages: int = 0) -> Tuple[str, float]:
    """Classify a document based on filename and content.

    When the filename is uninformative (UUID, numeric), content-based
    classification gets extra weight. Section heading detection provides
    additional signal for structured documents.

    Args:
        filename: Document filename
        text: First ~2000 chars of document text
        pages: Number of pages in document

    Returns:
        (doc_type, confidence) where doc_type is one of:
        'main', 'conditions', 'criteria', 'costs', 'skip', 'unknown'
    """
    fname_lower = _normalize(filename)
    # Use more text for content analysis (up to 4000 chars)
    text_sample = text[:4000].lower() if text else ""

    uninformative_fname = _is_uninformative_filename(filename)

    best_type = "unknown"
    best_score = 0.0

    for doc_type, rules in CLASSIFICATION_RULES.items():
        score = 0.0

        # Filename matching (highest weight — unless filename is uninformative)
        if not uninformative_fname:
            fname_hits = _count_keyword_hits(fname_lower, rules["filename_keywords"])
            if fname_hits > 0:
                score += 0.3 + 0.2 * min(fname_hits / max(len(rules["filename_keywords"]), 1), 1.0)

            # Negative filename matching (reduces score)
            if rules.get("filename_negative"):
                neg_hits = _count_keyword_hits(fname_lower, rules["filename_negative"])
                if neg_hits > 0 and doc_type != "skip":
                    score -= 0.3

        # Content keyword matching
        if text_sample and rules["content_keywords"]:
            content_hits = _count_keyword_hits(text_sample, rules["content_keywords"])
            content_ratio = content_hits / max(len(rules["content_keywords"]), 1)
            # Higher weight for content when filename is uninformative
            content_weight = 0.6 if uninformative_fname else 0.4
            score += content_weight * min(content_ratio, 1.0)

        # Section heading detection (strong structural signal)
        sections = rules.get("content_sections", [])
        if text_sample and sections:
            section_hits = _count_section_hits(text_sample, sections)
            if section_hits > 0:
                section_weight = 0.3 if uninformative_fname else 0.15
                score += section_weight * min(section_hits / max(len(sections), 1), 1.0)

        # Page count bonus
        min_pages = rules.get("min_pages", 0)
        if pages > 0 and min_pages > 0:
            if pages >= min_pages:
                score += 0.1

        if score > best_score:
            best_score = score
            best_type = doc_type

    # Lower threshold for content-based classification
    threshold = 0.05 if uninformative_fname else 0.1

    if best_score < threshold:
        if text_sample and len(text_sample) > 500:
            return "main", 0.1  # default to main for substantial documents
        return "unknown", 0.0

    # Normalize confidence to 0-1
    confidence = min(best_score, 1.0)

    if uninformative_fname:
        log.debug(f"Content-based classification for '{filename}': {best_type} ({confidence:.2f})")

    return best_type, confidence

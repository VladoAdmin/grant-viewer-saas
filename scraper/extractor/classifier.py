"""Rule-based document classifier.

Classifies documents into categories based on filename and content keywords.
Reuses classification rules from PRD Appendix B and universal_extractor.py.
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
            "hodnotiace kritériá",
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
        "filename_negative": [],
        "min_pages": 0,
        "priority": 0,
    },
}


def _normalize(text: str) -> str:
    """Normalize text for matching (lowercase, remove diacritics-insensitive)."""
    return text.lower().strip()


def _count_keyword_hits(text: str, keywords: list) -> int:
    """Count how many keywords appear in the text."""
    text_lower = text.lower()
    return sum(1 for kw in keywords if kw.lower() in text_lower)


def classify_document(filename: str, text: str = "", pages: int = 0) -> Tuple[str, float]:
    """Classify a document based on filename and content.

    Args:
        filename: Document filename
        text: First ~2000 chars of document text
        pages: Number of pages in document

    Returns:
        (doc_type, confidence) where doc_type is one of:
        'main', 'conditions', 'criteria', 'costs', 'skip', 'unknown'
    """
    fname_lower = _normalize(filename)
    text_sample = text[:2000].lower() if text else ""

    best_type = "unknown"
    best_score = 0.0

    for doc_type, rules in CLASSIFICATION_RULES.items():
        score = 0.0

        # Filename matching (highest weight)
        fname_hits = _count_keyword_hits(fname_lower, rules["filename_keywords"])
        if fname_hits > 0:
            # Even one filename match is strong signal
            score += 0.3 + 0.2 * min(fname_hits / max(len(rules["filename_keywords"]), 1), 1.0)

        # Negative filename matching (reduces score)
        if rules.get("filename_negative"):
            neg_hits = _count_keyword_hits(fname_lower, rules["filename_negative"])
            if neg_hits > 0 and doc_type != "skip":
                score -= 0.3

        # Content matching
        if text_sample and rules["content_keywords"]:
            content_hits = _count_keyword_hits(text_sample, rules["content_keywords"])
            score += 0.4 * min(content_hits / max(len(rules["content_keywords"]), 1), 1.0)

        # Page count bonus
        min_pages = rules.get("min_pages", 0)
        if pages > 0 and min_pages > 0:
            if pages >= min_pages:
                score += 0.1

        if score > best_score:
            best_score = score
            best_type = doc_type

    # If nothing matched well, default to 'unknown' or 'main' with low confidence
    if best_score < 0.1:
        if text_sample and len(text_sample) > 500:
            return "main", 0.1  # default to main for substantial documents
        return "unknown", 0.0

    # Normalize confidence to 0-1
    confidence = min(best_score, 1.0)
    return best_type, confidence

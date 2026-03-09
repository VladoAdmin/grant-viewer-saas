"""Attribute extraction from classified grant call documents.

Extracts structured attributes (kod_vyzvy, datum_vyhlasenia, deadline,
celkova_alokacia, etc.) from PDF/DOCX text using:
  1. Regex-first for structured fields (codes, dates, amounts, percentages)
  2. GPT-4o-mini fallback for complex free-text fields (eligible applicants,
     activities, specific objectives)

Input: List of document dicts with 'text', 'doc_type', 'filename'
Output: Dict[str, str] — key-value extracted attributes
"""

import json
import logging
import re
from typing import Dict, List, Optional

from openai import OpenAI

from ..config import OPENAI_API_KEY

log = logging.getLogger(__name__)

_oai: Optional[OpenAI] = None


def _get_openai() -> OpenAI:
    global _oai
    if _oai is None:
        _oai = OpenAI(api_key=OPENAI_API_KEY, timeout=60.0)
    return _oai


# ---------------------------------------------------------------------------
# Regex extraction helpers
# ---------------------------------------------------------------------------

def _extract_call_code(text: str) -> Optional[str]:
    """Extract grant call code (e.g. PSK-SIEA-006-2024-DV-FST)."""
    # Pattern: PSK-XXX-NNN-YYYY-... or similar codes with at least 3 dash-segments
    patterns = [
        r'(?:kód\s+výzvy|kód\s*:\s*)\s*([A-Z]{2,5}-[A-Z0-9]+-[0-9]+-[0-9]{4}[A-Z0-9-]*)',
        r'\b(PSK-[A-Z]+-\d{3}-\d{4}-[A-Z0-9-]+)\b',
        r'\b(IROP-[A-Z0-9]+-\d{3}-\d{4}[A-Z0-9-]*)\b',
        r'\b(OPII-[A-Z0-9]+-\d{3}-\d{4}[A-Z0-9-]*)\b',
        r'\b([A-Z]{2,5}-[A-Z]{2,10}-\d{3}-\d{4}-[A-Z]{2}(?:-[A-Z]{2,5})+)\b',
    ]
    for pat in patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            return m.group(1).upper().strip()
    return None


def _extract_dates(text: str) -> Dict[str, Optional[str]]:
    """Extract announcement and deadline dates."""
    results: Dict[str, Optional[str]] = {
        "datum_vyhlasenia": None,
        "deadline": None,
    }

    # Common date pattern: DD.MM.YYYY or DD. MM. YYYY (with optional spaces)
    _DATE_DD_MM_YYYY = r'(\d{1,2})\s*\.\s*(\d{1,2})\s*\.\s*(\d{4})'

    # Look for announcement date patterns
    # Allow multiline gap (up to 50 chars) between label and date
    announce_patterns = [
        r'(?:dátum\s+vyhlásenia\s+výzvy|dátum\s+vyhlásenia|vyhlásená\s+dňa|vyhlásenie\s+výzvy)[:\s]*' + _DATE_DD_MM_YYYY,
        r'(?:dátum\s+vyhlásenia\s+výzvy|dátum\s+vyhlásenia|vyhlásená\s+dňa)[:\s\n]*' + _DATE_DD_MM_YYYY,
        # Reversed: date before label
        _DATE_DD_MM_YYYY + r'\s*\n?\s*(?:dátum\s+vyhlásenia)',
        r'(?:dátum\s+vyhlásenia|vyhlásená\s+dňa|vyhlásenie\s+výzvy)[:\s]*(\d{4})-(\d{2})-(\d{2})',
    ]
    for pat in announce_patterns:
        m = re.search(pat, text, re.IGNORECASE | re.DOTALL)
        if m:
            groups = m.groups()
            if len(groups[0]) == 4:
                # YYYY-MM-DD format
                results["datum_vyhlasenia"] = f"{groups[0]}-{groups[1]}-{groups[2]}"
            else:
                # DD.MM.YYYY format
                results["datum_vyhlasenia"] = f"{groups[2]}-{int(groups[1]):02d}-{int(groups[0]):02d}"
            break

    # Look for deadline patterns
    deadline_patterns = [
        r'(?:uzávierka|uzatvoren|dátum\s+uzavretia|termín\s+uzavretia|termín\s+na\s+predloženie|predkladanie\s+(?:žiadostí|ŽoNFP)\s+(?:je\s+)?(?:do|najneskôr)?)[:\s]*' + _DATE_DD_MM_YYYY,
        r'(?:uzávierka|uzatvoren|termín\s+uzavretia|termín\s+na\s+predloženie)[:\s]*(\d{4})-(\d{2})-(\d{2})',
        r'(?:do\s+vyčerpania|priebežn|otvorená)',
    ]
    for pat in deadline_patterns:
        m = re.search(pat, text, re.IGNORECASE | re.DOTALL)
        if m:
            groups = m.groups()
            if not groups:
                # "do vyčerpania" / "priebežná" type
                results["deadline"] = "do vyčerpania alokácie"
                break
            if len(groups[0]) == 4:
                results["deadline"] = f"{groups[0]}-{groups[1]}-{groups[2]}"
            else:
                results["deadline"] = f"{groups[2]}-{int(groups[1]):02d}-{int(groups[0]):02d}"
            break

    return results


def _extract_allocation(text: str) -> Optional[str]:
    """Extract total allocation amount in EUR."""
    # Patterns for allocation amounts - look for large numbers near allocation keywords
    # NOTE: In ITMS PDF exports, the amount often appears BEFORE the label
    patterns = [
        # "15 828 201,00 €" followed by "Výška finančných prostriedkov" (amount before label)
        r'(\d[\d\s,.]+)\s*(?:EUR|€|eur)\s*\n?\s*(?:výška\s+finančných\s+prostriedkov|celkov[áa]\s+(?:indikatívna\s+)?výška|indikatívna\s+výška)',
        # "alokácia ... 15 828 201,00 €" (label before amount, multiline)
        r'(?:celkov[áa]\s+(?:indikatívna\s+)?výška|alokácia|výška\s+finančných\s+prostriedkov|finančné\s+prostriedky|indikatívna\s+výška)[^€]{0,200}?(\d[\d\s,.]+)\s*(?:EUR|€|eur)',
        r'(?:alokáci[aí]|indikatívna\s+výška)[^€]{0,200}?(\d[\d\s,.]+)\s*(?:EUR|€|eur)',
        # Standalone "NN NNN NNN,NN €" pattern (large amounts near relevant text)
        r'(\d{1,3}(?:\s\d{3}){2,}(?:,\d{2})?)\s*€',
    ]

    for pat in patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            raw = m.group(1).strip()
            # Clean: remove spaces, replace comma decimal with dot
            cleaned = raw.replace(" ", "").replace("\xa0", "")
            # Handle European number format: 15.828.201,00 or 15828201,00
            if "," in cleaned and "." in cleaned:
                # 15.828.201,00 format
                cleaned = cleaned.replace(".", "").replace(",", ".")
            elif "," in cleaned:
                # Could be 15828201,00 (decimal comma)
                parts = cleaned.split(",")
                if len(parts) == 2 and len(parts[1]) <= 2:
                    cleaned = parts[0]  # Take integer part
                else:
                    cleaned = cleaned.replace(",", "")
            elif "." in cleaned:
                # Could be 15.828.201 (thousands separator) or 15828201.00
                parts = cleaned.split(".")
                if len(parts[-1]) <= 2 and len(parts) == 2:
                    cleaned = parts[0]  # 15828201.00 -> 15828201
                else:
                    cleaned = cleaned.replace(".", "")  # 15.828.201 -> 15828201

            try:
                val = int(float(cleaned))
                if val >= 10000:  # Sanity: at least 10K EUR
                    return str(val)
            except (ValueError, OverflowError):
                continue
    return None


def _extract_provider(text: str) -> Optional[str]:
    """Extract provider/ministry name."""
    patterns = [
        # "Poskytovateľ Riadiaci orgán PSK - Ministerstvo ... SR" (multiline)
        r'(?:poskytovateľ)\s+(?:riadiaci\s+orgán\s+PSK\s*[-–]\s*)?(Ministerstvo[\s\S]{10,200}?SR)\s+(?:ako\s+riadiaci|vyhlasuje)',
        r'(?:poskytovateľ|vyhlasovateľ)[:\s]+(?:je\s+)?([\s\S]{10,200}?)(?:\s+ako\s+riadiaci|\s+vyhlasuje)',
        r'(Ministerstvo\s+(?:investícií|životného\s+prostredia|hospodárstva|školstva|dopravy|pôdohospodárstva|zdravotníctva|práce|vnútra|financií|kultúry|obrany|spravodlivosti)[\s\S]{0,100}?SR)',
        r'(Slovenská\s+inovačná\s+a\s+energetická\s+agentúra)',
        r'(Slovenská\s+agentúra\s+životného\s+prostredia)',
        r'(Výskumná\s+agentúra)',
    ]
    for pat in patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            val = m.group(1) if m.lastindex else m.group(0)
            # Clean up: collapse whitespace, remove trailing comma
            val = re.sub(r'\s+', ' ', val).strip().rstrip(',').strip()
            return val[:300]
    return None


def _extract_cofinancing(text: str) -> Optional[str]:
    """Extract co-financing rate (percentage)."""
    patterns = [
        r'(?:miera\s+spolufinancovania|spolufinancovanie)[:\s]*(?:je\s+)?(\d{1,3}(?:[,.]\d{1,2})?)\s*%',
        r'(?:maximáln\w+\s+)?miera\s+spolufinancovania\s+(?:z\s+)?(?:prostriedkov\s+)?(?:EÚ|ŠR)[:\s]*(\d{1,3}(?:[,.]\d{1,2})?)\s*%',
        r'(\d{1,3})\s*%\s*(?:z\s+celkových\s+oprávnených\s+výdavkov)',
    ]
    for pat in patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            return m.group(1).replace(",", ".").strip() + " %"
    return None


def _extract_contribution_range(text: str) -> Dict[str, Optional[str]]:
    """Extract min/max contribution amounts."""
    results: Dict[str, Optional[str]] = {
        "min_prispevok": None,
        "max_prispevok": None,
    }

    min_patterns = [
        r'(?:minimáln\w+\s+(?:výška\s+)?príspev\w+|minimáln\w+\s+výška\s+(?:ŽoNFP|NFP|žiadosti))[:\s]*(\d[\d\s,.]+)\s*(?:EUR|€|eur)',
        r'(?:min\.\s+(?:výška\s+)?príspev\w+|min\.\s+NFP)[:\s]*(\d[\d\s,.]+)\s*(?:EUR|€|eur)',
    ]
    max_patterns = [
        r'(?:maximáln\w+\s+(?:výška\s+)?príspev\w+|maximáln\w+\s+výška\s+(?:ŽoNFP|NFP|žiadosti))[:\s]*(\d[\d\s,.]+)\s*(?:EUR|€|eur)',
        r'(?:max\.\s+(?:výška\s+)?príspev\w+|max\.\s+NFP)[:\s]*(\d[\d\s,.]+)\s*(?:EUR|€|eur)',
    ]

    def _clean_amount(raw: str) -> Optional[str]:
        cleaned = raw.replace(" ", "").replace("\xa0", "")
        if "," in cleaned and "." in cleaned:
            cleaned = cleaned.replace(".", "").replace(",", ".")
        elif "," in cleaned:
            parts = cleaned.split(",")
            if len(parts) == 2 and len(parts[1]) <= 2:
                cleaned = parts[0]
            else:
                cleaned = cleaned.replace(",", "")
        elif "." in cleaned:
            parts = cleaned.split(".")
            if len(parts[-1]) <= 2 and len(parts) == 2:
                cleaned = parts[0]
            else:
                cleaned = cleaned.replace(".", "")
        try:
            return str(int(float(cleaned)))
        except (ValueError, OverflowError):
            return None

    for pat in min_patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            results["min_prispevok"] = _clean_amount(m.group(1))
            break

    for pat in max_patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            results["max_prispevok"] = _clean_amount(m.group(1))
            break

    return results


def _extract_program_name(text: str) -> Optional[str]:
    """Extract program name."""
    patterns = [
        r'(Program\s+Slovensko\s*(?:2021\s*[-–]\s*2027)?)',
        r'(?:pre\s+program\s+)(Program\s+[A-Z][a-záäčďéěíĺľňóôŕřšťúůýžA-Z\s]{2,50}?)(?:\s*[-–]|\s*\n)',
        r'(?:názov\s+programu)[:\s]+(?:je\s+)?([^\n]{5,100})',
        r'(Operačný\s+program\s+[^\n]{5,80})',
    ]
    for pat in patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            val = m.group(1) if m.lastindex else m.group(0)
            val = re.sub(r'\s+', ' ', val).strip()
            if len(val) > 5:
                return val[:300]
    return None


# ---------------------------------------------------------------------------
# Regex-based extraction (Phase 1)
# ---------------------------------------------------------------------------

def extract_regex_attributes(text: str) -> Dict[str, str]:
    """Extract all regex-matchable attributes from document text."""
    attrs: Dict[str, str] = {}

    code = _extract_call_code(text)
    if code:
        attrs["kod_vyzvy"] = code

    dates = _extract_dates(text)
    for k, v in dates.items():
        if v:
            attrs[k] = v

    alloc = _extract_allocation(text)
    if alloc:
        attrs["celkova_alokacia"] = alloc

    provider = _extract_provider(text)
    if provider:
        attrs["poskytovatel"] = provider

    program = _extract_program_name(text)
    if program:
        attrs["nazov_programu"] = program

    cofinancing = _extract_cofinancing(text)
    if cofinancing:
        attrs["miera_spolufinancovania"] = cofinancing

    contrib = _extract_contribution_range(text)
    for k, v in contrib.items():
        if v:
            attrs[k] = v

    return attrs


# ---------------------------------------------------------------------------
# GPT-4o-mini extraction (Phase 2 — complex attributes)
# ---------------------------------------------------------------------------

_GPT_EXTRACTION_PROMPT = """Analyzuj nasledujúci text z výzvy na predkladanie žiadostí o NFP (nenávratný finančný príspevok).
Extrahuj tieto atribúty (ak sa nachádzajú v texte):

1. opravneni_ziadatelia — kto môže podať žiadosť (typ organizácií, právna forma)
2. opravnene_aktivity — aké aktivity/činnosti sú podporované
3. specificke_ciele — špecifické ciele programu/výzvy
4. opravnene_uzemie — kde sa môžu projekty realizovať (kraje, okresy, celé SK)

Pravidlá:
- Extrahuj LEN informácie explicitne uvedené v texte
- Ak atribút nie je v texte, vráť null
- Stručne ale presne (max 500 znakov na atribút)
- Odpovedaj VÝHRADNE v JSON formáte

JSON formát odpovede:
{
  "opravneni_ziadatelia": "...",
  "opravnene_aktivity": "...",
  "specificke_ciele": "...",
  "opravnene_uzemie": "..."
}"""


def extract_gpt_attributes(text: str) -> Dict[str, str]:
    """Use GPT-4o-mini to extract complex free-text attributes.

    Sends at most ~8000 chars of text to keep costs minimal (~$0.005/call).
    """
    if not OPENAI_API_KEY:
        log.warning("OPENAI_API_KEY not set, skipping GPT attribute extraction")
        return {}

    # Truncate text to ~8000 chars for cost efficiency
    # Focus on beginning (usually has key info) and a chunk from middle
    if len(text) > 8000:
        text_sample = text[:5000] + "\n\n[...]\n\n" + text[len(text)//2:len(text)//2+3000]
    else:
        text_sample = text

    try:
        oai = _get_openai()
        resp = oai.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": _GPT_EXTRACTION_PROMPT},
                {"role": "user", "content": text_sample},
            ],
            temperature=0.0,
            max_tokens=1000,
            response_format={"type": "json_object"},
        )
        content = resp.choices[0].message.content
        if not content:
            return {}

        data = json.loads(content)
        attrs: Dict[str, str] = {}
        for key in ("opravneni_ziadatelia", "opravnene_aktivity", "specificke_ciele", "opravnene_uzemie"):
            val = data.get(key)
            if val and isinstance(val, str) and val.strip().lower() not in ("null", "n/a", ""):
                attrs[key] = val.strip()[:2000]

        log.info(f"GPT extraction: found {len(attrs)} complex attributes")
        return attrs

    except Exception as e:
        log.warning(f"GPT attribute extraction failed: {e}")
        return {}


# ---------------------------------------------------------------------------
# Document version sorting
# ---------------------------------------------------------------------------

def _is_tracked_changes(doc: Dict) -> bool:
    """Check if a document is a tracked-changes (SZ) version.

    SZ = "Sledovanie Zmien" (track changes) — these contain concatenated
    old+new values that break regex extraction. Skip them.
    "bez_SZ" means "without tracked changes" and is the CLEAN version — keep it.
    """
    fname = doc.get("filename", "")
    # _SZ.pdf or _SZ.docx at end of name, but NOT "bez_SZ"
    if re.search(r'(?<!bez)_SZ\b', fname):
        return True
    return False


def _version_key(doc: Dict) -> int:
    """Extract version number from filename for sorting.

    Files with U1, U2, U3 suffixes represent update versions.
    Higher numbers = newer versions. No version = 0 (original).
    """
    fname = doc.get("filename", "")
    # Match _U1, _U2, _U3, _U_3 etc. in filename
    m = re.search(r'[_\s]U[_]?(\d+)', fname, re.IGNORECASE)
    if m:
        return int(m.group(1))
    # Match "zmena č. 1", "aktualizácia č. 2" etc.
    m = re.search(r'(?:zmena|aktualizáci[aí])\s*(?:č\.\s*)?(\d+)', fname, re.IGNORECASE)
    if m:
        return int(m.group(1))
    return 0


def _sort_by_version(documents: List[Dict]) -> List[Dict]:
    """Sort documents so newer versions come last (will overwrite older).

    Also filters out tracked-changes (_SZ) documents that contain
    concatenated old+new values breaking extraction.
    """
    # Filter out SZ (tracked changes) documents
    clean_docs = [d for d in documents if not _is_tracked_changes(d)]
    if not clean_docs:
        clean_docs = documents  # Fallback: use all if everything is SZ

    return sorted(clean_docs, key=_version_key)


# ---------------------------------------------------------------------------
# Main extraction entry point
# ---------------------------------------------------------------------------

def extract_attributes(documents: List[Dict]) -> Dict[str, str]:
    """Extract attributes from classified documents.

    Processes documents of type 'main' and 'conditions' (most info-rich).
    Regex extraction runs on all qualifying docs, GPT on the longest/best one.

    Args:
        documents: List of dicts with keys: text, doc_type, filename

    Returns:
        Dict[str, str] — merged attributes from all documents
    """
    # Filter for documents likely to contain structured info
    target_types = {"main", "conditions"}
    target_docs = [d for d in documents if d.get("doc_type") in target_types]

    if not target_docs:
        # Fallback: try all non-skip documents
        target_docs = [d for d in documents if d.get("doc_type") != "skip"]

    if not target_docs:
        log.info("No suitable documents for attribute extraction")
        return {}

    # Sort target docs to process older versions first, newer last
    # (so newer versions overwrite older ones via "last write wins")
    target_docs_sorted = _sort_by_version(target_docs)

    # Phase 1: Regex extraction on all target documents
    all_regex_attrs: Dict[str, str] = {}
    best_doc_text = ""
    best_doc_len = 0

    for doc in target_docs_sorted:
        text = doc.get("text", "")
        if not text or len(text) < 100:
            continue

        regex_attrs = extract_regex_attributes(text)
        # Merge: later docs OVERWRITE earlier ones (last/newest version wins)
        all_regex_attrs.update(regex_attrs)

        # Track longest doc for GPT extraction
        if len(text) > best_doc_len:
            best_doc_len = len(text)
            best_doc_text = text

    log.info(f"Regex extraction: found {len(all_regex_attrs)} attributes from {len(target_docs)} docs")

    # Phase 2: GPT extraction on the best document (for complex fields)
    gpt_attrs: Dict[str, str] = {}
    missing_complex = {"opravneni_ziadatelia", "opravnene_aktivity", "specificke_ciele", "opravnene_uzemie"}
    already_found = missing_complex.intersection(all_regex_attrs.keys())
    still_missing = missing_complex - already_found

    if still_missing and best_doc_text:
        log.info(f"Running GPT extraction for {len(still_missing)} missing complex attributes")
        gpt_attrs = extract_gpt_attributes(best_doc_text)

    # Merge: regex first, GPT fills gaps
    merged = {**gpt_attrs, **all_regex_attrs}

    log.info(f"Total extracted attributes: {len(merged)} "
             f"(regex={len(all_regex_attrs)}, gpt={len(gpt_attrs)})")

    return merged

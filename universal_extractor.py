#!/usr/bin/env python3
"""
Universal Grant Document Extraction System
Supports: ENVIROFOND, FNPS, APVV, FPU, ITMS21
"""

import requests
import zipfile
import io
import fitz
import json
import re
from pathlib import Path
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass
from enum import Enum

class SourceType(Enum):
    ENVIROFOND = "envirofond"
    FNPS = "fnps"
    APVV = "apvv"
    FPU = "fpu"
    ITMS21 = "itms21"
    ISPP_APA = "ispp.apa.sk"
    PLANOBNOVY = "planobnovy.sk"
    SIEA = "siea.sk"
    NADACIA_ESET = "nadaciaeset.sk"
    NADACIA_NBS = "nadacianbs.sk"
    CULTURE_GOV = "culture.gov.sk"
    UNKNOWN = "unknown"

@dataclass
class DocumentInfo:
    url: str
    filename: str
    doc_type: str  # 'main', 'conditions', 'criteria', 'costs', 'form', 'skip'
    priority: int

@dataclass
class ExtractionResult:
    source: str
    call_id: str
    text: str
    text_length: int
    structure: Dict[str, bool]
    similarity_score: int
    documents_processed: List[str]


class SourceHandler:
    """Base class for source-specific handling."""
    
    def detect(self, urls: List[str]) -> bool:
        raise NotImplementedError
    
    def classify_documents(self, urls: List[str]) -> List[DocumentInfo]:
        raise NotImplementedError
    
    def download_and_extract(self, url: str) -> Tuple[Optional[str], Optional[str]]:
        """Returns (text, error)"""
        try:
            headers = {"User-Agent": "Mozilla/5.0"}
            r = requests.get(url, headers=headers, timeout=60)
            
            if r.status_code != 200:
                return None, f"HTTP {r.status_code}"
            
            content = r.content
            
            # Check if ZIP
            if content[:2] == b'PK':
                content = self._extract_from_zip(content)
                if not content:
                    return None, "No PDF in ZIP"
            
            # Extract text from PDF
            return self._extract_pdf_text(content), None
            
        except Exception as e:
            return None, str(e)
    
    def _extract_from_zip(self, content: bytes) -> Optional[bytes]:
        """Extract main PDF from ZIP."""
        try:
            with zipfile.ZipFile(io.BytesIO(content)) as z:
                pdf_files = [n for n in z.namelist() if n.lower().endswith('.pdf')]
                if not pdf_files:
                    return None
                
                # Find main document
                main_pdf = None
                for p in pdf_files:
                    p_lower = p.lower()
                    if any(x in p_lower for x in ['vyzva', 'výzva', '01_vyzva', '00_zmena']):
                        if not any(x in p_lower for x in ['priloha', 'attachment']):
                            main_pdf = p
                            break
                
                if not main_pdf:
                    main_pdf = pdf_files[0]
                
                with z.open(main_pdf) as f:
                    return f.read()
        except:
            return None
    
    def _extract_pdf_text(self, content: bytes, max_pages: int = 25) -> str:
        """Extract text from PDF bytes."""
        doc = fitz.open(stream=content, filetype="pdf")
        text = ""
        for i in range(min(max_pages, len(doc))):
            text += doc[i].get_text() + "\n"
        doc.close()
        return text
    
    def analyze_structure(self, text: str) -> Dict[str, bool]:
        """Analyze document structure."""
        text_lower = text.lower()
        return {
            'has_basic': any(x in text_lower for x in ['názov', 'kód', 'výzva', 'alokácia', 'deadline']),
            'has_conditions': any(x in text_lower for x in ['podmienky', 'podmienka', 'oprávnenosť']),
            'has_costs': any(x in text_lower for x in ['náklady', 'rozpočet', 'výdavky', 'financovanie']),
            'has_criteria': any(x in text_lower for x in ['kritériá', 'hodnotenie', 'vyhodnotenie']),
        }


class EnvirofondHandler(SourceHandler):
    """Handler for Envirofond documents.
    
    Structure: PDF/DOCX on envirofond.sk/wp-content/uploads/
    Types: Výzva (main), Špecifikácia (main), Príručka (conditions),
           Hodnotiace kritériá (criteria), Úverové podmienky (conditions)
    Skip: GDPR, manuály, formuláre, vzory, čestné vyhlásenia
    """
    
    def detect(self, urls: List[str]) -> bool:
        return any('envirofond' in u.lower() for u in urls)
    
    def classify_documents(self, urls: List[str]) -> List[DocumentInfo]:
        docs = []
        for url in urls:
            fname = url.split('/')[-1].lower()
            
            # Skip: forms, GDPR, manuals, templates, declarations
            if any(x in fname for x in ['formular', 'gdpr', 'manual', 'pouzivatelsky',
                    'vzor', 'cestne-vyhlasenie', 'cestne_vyhlasenie', 'zaverecny-odpocet',
                    'kalkulac', 'ziadost-o', 'ziadost_o', 'hospodarsk', 'uzemna-prislusnost']):
                docs.append(DocumentInfo(url, fname, 'skip', 0))
            # Main: výzva, špecifikácia, všeobecné podmienky, usmernenie
            elif ('vyzva' in fname or 'specifikacia' in fname or 'specifikácia' in fname
                  or 'vseobecne-uverove' in fname or 'vseobecne_uverove' in fname
                  or 'usmernenie' in fname):
                if not any(x in fname for x in ['priloha', 'zmena']):
                    docs.append(DocumentInfo(url, fname, 'main', 1))
                else:
                    docs.append(DocumentInfo(url, fname, 'conditions', 3))
            # Criteria: príloha 2, hodnotiace
            elif 'priloha-c-2' in fname or 'priloha-c.-2' in fname or 'hodnotiace' in fname:
                docs.append(DocumentInfo(url, fname, 'criteria', 2))
            # Conditions: príloha 1, príručka, oprávnení žiadatelia
            elif ('priloha-c-1' in fname or 'priloha-c.-1' in fname or 'prirucka' in fname
                  or 'opravnen' in fname or 'zoznam-opravnenych' in fname):
                docs.append(DocumentInfo(url, fname, 'conditions', 3))
            # Zmluva - conditions
            elif 'zmluva' in fname:
                docs.append(DocumentInfo(url, fname, 'conditions', 4))
            # Other PDFs - include with low priority
            elif fname.endswith('.pdf'):
                docs.append(DocumentInfo(url, fname, 'other', 5))
        
        return sorted([d for d in docs if d.doc_type != 'skip'], key=lambda x: x.priority)


class FPUHandler(SourceHandler):
    """Handler for FPU (Fond na podporu umenia) documents."""
    
    def detect(self, urls: List[str]) -> bool:
        return any('fpu.sk' in u.lower() for u in urls)
    
    def classify_documents(self, urls: List[str]) -> List[DocumentInfo]:
        docs = []
        for url in urls:
            fname = url.split('/')[-1].lower()
            
            # Main document
            if fname.startswith('vyzva-') and fname.endswith('.pdf'):
                docs.append(DocumentInfo(url, fname, 'main', 1))
            # Look for criteria/conditions in other PDFs
            elif any(x in fname for x in ['kriteria', 'hodnotenie']):
                docs.append(DocumentInfo(url, fname, 'criteria', 2))
            elif any(x in fname for x in ['podmienky', 'technicke']):
                docs.append(DocumentInfo(url, fname, 'conditions', 3))
        
        return sorted(docs, key=lambda x: x.priority)


class APVVHandler(SourceHandler):
    """Handler for APVV documents."""
    
    def detect(self, urls: List[str]) -> bool:
        return any('apvv.sk' in u.lower() for u in urls)
    
    def classify_documents(self, urls: List[str]) -> List[DocumentInfo]:
        docs = []
        for url in urls:
            fname = url.split('/')[-1].lower()
            
            # Main document - "znenie vyzvy"
            if 'znenie-vyzvy' in fname or ('vyzva' in fname and 'priloha' not in fname):
                docs.append(DocumentInfo(url, fname, 'main', 1))
            # Priloha 2 - criteria
            elif 'priloha2' in fname or '_2_' in fname:
                docs.append(DocumentInfo(url, fname, 'criteria', 2))
            # Priloha 1 - conditions
            elif 'priloha1' in fname or '_1_' in fname:
                docs.append(DocumentInfo(url, fname, 'conditions', 3))
            # Priloha 3 - costs
            elif 'priloha3' in fname or '_3_' in fname:
                docs.append(DocumentInfo(url, fname, 'costs', 4))
            # Skip forms (4-9)
            elif any(f'priloha{x}' in fname or f'_{x}_' in fname for x in ['4', '5', '6', '7', '8', '9']):
                docs.append(DocumentInfo(url, fname, 'skip', 0))
            # Skip laws and manuals
            elif any(x in fname for x in ['zakon', 'manual', 'formular']):
                docs.append(DocumentInfo(url, fname, 'skip', 0))
        
        return sorted(docs, key=lambda x: x.priority)


class ITMS21Handler(SourceHandler):
    """Handler for ITMS21 documents."""
    
    def detect(self, urls: List[str]) -> bool:
        return any('itms21' in u.lower() for u in urls)
    
    def classify_documents(self, urls: List[str]) -> List[DocumentInfo]:
        # For ITMS21, we need to download first to check if ZIP
        # Return all URLs as potential candidates
        docs = []
        for url in urls:
            # Extract filename from fragment if present
            if '#' in url:
                fname = url.split('#')[1]
            else:
                fname = url.split('/')[-1]
            
            # Try to classify by fragment name
            if any(x in fname.lower() for x in ['vyzva', 'výzva']):
                docs.append(DocumentInfo(url, fname, 'main', 1))
            elif any(x in fname.lower() for x in ['priloha 2', 'kriteria']):
                docs.append(DocumentInfo(url, fname, 'criteria', 2))
            elif any(x in fname.lower() for x in ['priloha 1']):
                docs.append(DocumentInfo(url, fname, 'conditions', 3))
            else:
                docs.append(DocumentInfo(url, fname, 'unknown', 5))
        
        return sorted(docs, key=lambda x: x.priority)


class FNPSHandler(SourceHandler):
    """Handler for FNPS documents."""
    
    def detect(self, urls: List[str]) -> bool:
        return any(x in u.lower() for u in urls for x in ['fnps.sk', 'fondnapodporu'])
    
    def classify_documents(self, urls: List[str]) -> List[DocumentInfo]:
        docs = []
        for url in urls:
            fname = url.split('/')[-1].lower()
            
            if 'vyzva' in fname and fname.endswith('.pdf'):
                docs.append(DocumentInfo(url, fname, 'main', 1))
        
        return sorted(docs, key=lambda x: x.priority)


class UniversalExtractor:
    """Main extraction orchestrator."""
    
    def __init__(self):
        self.handlers = [
            EnvirofondHandler(),
            FPUHandler(),
            APVVHandler(),
            ITMS21Handler(),
            FNPSHandler(),
            ISPPApaHandler(),
            PlanobnoyHandler(),
            SIEAHandler(),
            NadaciaHandler(),
            CultureGovHandler(),
        ]
    
    def detect_source(self, urls: List[str]) -> SourceType:
        """Detect source type from URLs."""
        handler_type_map = {
            EnvirofondHandler: SourceType.ENVIROFOND,
            FPUHandler: SourceType.FPU,
            APVVHandler: SourceType.APVV,
            ITMS21Handler: SourceType.ITMS21,
            FNPSHandler: SourceType.FNPS,
            ISPPApaHandler: SourceType.ISPP_APA,
            PlanobnoyHandler: SourceType.PLANOBNOVY,
            SIEAHandler: SourceType.SIEA,
            NadaciaHandler: SourceType.NADACIA_ESET,
            CultureGovHandler: SourceType.CULTURE_GOV,  # detect differentiates via URL
        }
        for handler in self.handlers:
            if handler.detect(urls):
                return handler_type_map.get(type(handler), SourceType.UNKNOWN)
        return SourceType.UNKNOWN
    
    def get_handler(self, source: SourceType) -> Optional[SourceHandler]:
        """Get handler for source type."""
        handler_map = {
            SourceType.ENVIROFOND: EnvirofondHandler,
            SourceType.FPU: FPUHandler,
            SourceType.APVV: APVVHandler,
            SourceType.ITMS21: ITMS21Handler,
            SourceType.FNPS: FNPSHandler,
            SourceType.ISPP_APA: ISPPApaHandler,
            SourceType.PLANOBNOVY: PlanobnoyHandler,
            SourceType.SIEA: SIEAHandler,
            SourceType.NADACIA_ESET: NadaciaHandler,
            SourceType.NADACIA_NBS: NadaciaHandler,
            SourceType.CULTURE_GOV: CultureGovHandler,
        }
        
        handler_class = handler_map.get(source)
        if handler_class:
            return handler_class()
        return None
    
    def detect_source_by_name(self, source_name: str) -> SourceType:
        """Detect source type from DB source field (e.g. 'ispp.apa.sk')."""
        source_map = {
            'ispp.apa.sk': SourceType.ISPP_APA,
            'planobnovy.sk': SourceType.PLANOBNOVY,
            'siea.sk': SourceType.SIEA,
            'nadaciaeset.sk': SourceType.NADACIA_ESET,
            'nadacianbs.sk': SourceType.NADACIA_NBS,
            'culture.gov.sk': SourceType.CULTURE_GOV,
            'portal.itms21.sk': SourceType.ITMS21,
            'envirofond.sk': SourceType.ENVIROFOND,
            'apvv.sk': SourceType.APVV,
            'fpu.sk': SourceType.FPU,
        }
        for key, stype in source_map.items():
            if key in source_name.lower():
                return stype
        return SourceType.UNKNOWN

    def process_call(self, call_id: str, urls: List[str]) -> ExtractionResult:
        """Process a single grant call."""
        source = self.detect_source(urls)
        handler = self.get_handler(source)
        
        if not handler:
            return ExtractionResult(
                source=source.value,
                call_id=call_id,
                text="",
                text_length=0,
                structure={},
                similarity_score=0,
                documents_processed=[]
            )
        
        # Classify documents
        docs = handler.classify_documents(urls)
        
        # Process priority documents
        processed = []
        combined_text = ""
        
        for doc in docs:
            if doc.doc_type == 'skip':
                continue
            
            text, error = handler.download_and_extract(doc.url)
            if text:
                combined_text += f"\n\n=== {doc.filename} ===\n{text}"
                processed.append(doc.filename)
                
                # For 'main' documents, we might have enough
                if doc.doc_type == 'main' and len(text) > 10000:
                    break
        
        # Analyze structure
        structure = handler.analyze_structure(combined_text) if combined_text else {}
        similarity = sum(structure.values()) * 25 if structure else 0
        
        return ExtractionResult(
            source=source.value,
            call_id=call_id,
            text=combined_text,
            text_length=len(combined_text),
            structure=structure,
            similarity_score=similarity,
            documents_processed=processed
        )


# Usage example
if __name__ == "__main__":
    extractor = UniversalExtractor()
    
    # Test with sample URLs
    test_urls = [
        "https://envirofond.sk/wp-content/uploads/2026/02/Vyzva-B-1-rok-2026.pdf",
        "https://www.apvv.sk/buxus/docs/vyzvy/vseobecne/vv2024/vyzva-vv-2024-znenie-vyzvy_sk.pdf",
    ]
    
    print("Source detection test:")
    for url in test_urls:
        source = extractor.detect_source([url])
        print(f"  {url[:50]}... -> {source.value}")


# ============================================================
# NEW HANDLERS: ispp.apa.sk, planobnovy.sk, siea.sk, nadácie
# Added 2026-02-27
# ============================================================

class ISPPApaHandler(SourceHandler):
    """Handler for ispp.apa.sk (PPA - Pôdohospodárska platobná agentúra).
    
    Structure: DOCX/PDF via public API endpoints.
    Priority: plné znenie > príručka pre žiadateľa > ostatné prílohy.
    Supports DOCX extraction via python-docx.
    """
    
    def detect(self, urls: List[str]) -> bool:
        return any('apa.sk' in u.lower() or 'ispp' in u.lower() for u in urls)
    
    def classify_documents(self, urls: List[str]) -> List[DocumentInfo]:
        docs = []
        for url in urls:
            url_lower = url.lower()
            fname = url.split('/')[-1].lower()
            
            # Plné znenie (full text of the call)
            if 'plne-znenie' in url_lower or 'plné znenie' in fname:
                docs.append(DocumentInfo(url, fname, 'main', 1))
            # Príručka pre žiadateľa (applicant guide)
            elif 'prirucka' in url_lower or 'príručka' in fname:
                docs.append(DocumentInfo(url, fname, 'conditions', 2))
            # Identifikácia synergických účinkov
            elif 'synergick' in url_lower:
                docs.append(DocumentInfo(url, fname, 'criteria', 3))
            # Formuláre, vzory, registre - skip
            elif any(x in url_lower for x in ['formular', 'vzor', 'register', 'trestov', 'zoznam-plodin']):
                docs.append(DocumentInfo(url, fname, 'skip', 0))
            else:
                docs.append(DocumentInfo(url, fname, 'other', 5))
        
        return sorted([d for d in docs if d.doc_type != 'skip'], key=lambda x: x.priority)
    
    def download_and_extract(self, url: str) -> Tuple[Optional[str], Optional[str]]:
        """Download and extract - supports DOCX via python-docx."""
        try:
            headers = {"User-Agent": "Mozilla/5.0"}
            r = requests.get(url, headers=headers, timeout=60)
            if r.status_code != 200:
                return None, f"HTTP {r.status_code}"
            
            content = r.content
            
            # DOCX detection (PK magic + word/document.xml)
            if content[:2] == b'PK':
                try:
                    import docx
                    doc = docx.Document(io.BytesIO(content))
                    text = "\n".join([p.text for p in doc.paragraphs])
                    if text and len(text) > 200:
                        return text, None
                except:
                    pass
                # Fallback: try as ZIP with PDFs
                pdf_content = self._extract_from_zip(content)
                if pdf_content:
                    return self._extract_pdf_text(pdf_content), None
            
            # PDF
            if content[:5] == b'%PDF-':
                return self._extract_pdf_text(content), None
            
            return None, "Unknown format"
        except Exception as e:
            return None, str(e)


class PlanobnoyHandler(SourceHandler):
    """Handler for planobnovy.sk (Plán obnovy a odolnosti SR).
    
    Structure: Attachments are external URLs (sih.sk, vff.sk, minedu.sk, vaia.gov.sk).
    Scrapes web pages for content. Some have PDF attachments.
    Also scrapes the call_url page itself.
    """
    
    def detect(self, urls: List[str]) -> bool:
        return any('planobnovy.sk' in u.lower() for u in urls)
    
    def classify_documents(self, urls: List[str]) -> List[DocumentInfo]:
        docs = []
        for url in urls:
            url_lower = url.lower()
            fname = url.split('/')[-1].lower()
            
            if url_lower.endswith('.pdf'):
                docs.append(DocumentInfo(url, fname, 'main', 1))
            elif any(x in url_lower for x in ['aktuality', 'novinky', 'vyzva']):
                docs.append(DocumentInfo(url, fname, 'conditions', 2))
            else:
                docs.append(DocumentInfo(url, fname, 'other', 3))
        
        return sorted(docs, key=lambda x: x.priority)
    
    def download_and_extract(self, url: str) -> Tuple[Optional[str], Optional[str]]:
        """Scrape web pages or download PDFs."""
        try:
            headers = {"User-Agent": "Mozilla/5.0"}
            r = requests.get(url, headers=headers, timeout=60)
            if r.status_code != 200:
                return None, f"HTTP {r.status_code}"
            
            content = r.content
            
            # PDF
            if content[:5] == b'%PDF-':
                return self._extract_pdf_text(content), None
            
            # HTML - scrape content
            if b'<html' in content[:1000].lower() or b'<!doctype' in content[:500].lower():
                from bs4 import BeautifulSoup
                soup = BeautifulSoup(content, 'html.parser')
                for tag in soup(['script', 'style', 'nav', 'footer', 'header', 'aside']):
                    tag.decompose()
                main = soup.find('main') or soup.find('article') or soup.find('div', class_=re.compile('content|main'))
                text = main.get_text(separator='\n', strip=True) if main else soup.get_text(separator='\n', strip=True)
                if text and len(text) > 200:
                    return text, None
            
            return None, "No extractable content"
        except Exception as e:
            return None, str(e)


class SIEAHandler(SourceHandler):
    """Handler for siea.sk (Slovenská inovačná a energetická agentúra).
    
    Structure: No attachments in DB. Scrapes call_url pages directly.
    """
    
    def detect(self, urls: List[str]) -> bool:
        return any('siea.sk' in u.lower() for u in urls)
    
    def classify_documents(self, urls: List[str]) -> List[DocumentInfo]:
        docs = []
        for url in urls:
            fname = url.split('/')[-1].lower()
            if url.lower().endswith('.pdf'):
                docs.append(DocumentInfo(url, fname, 'main', 1))
            else:
                docs.append(DocumentInfo(url, fname, 'main', 2))
        return sorted(docs, key=lambda x: x.priority)
    
    def download_and_extract(self, url: str) -> Tuple[Optional[str], Optional[str]]:
        """Scrape SIEA web pages."""
        try:
            headers = {"User-Agent": "Mozilla/5.0"}
            r = requests.get(url, headers=headers, timeout=60)
            if r.status_code != 200:
                return None, f"HTTP {r.status_code}"
            
            content = r.content
            
            if content[:5] == b'%PDF-':
                return self._extract_pdf_text(content), None
            
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(content, 'html.parser')
            for tag in soup(['script', 'style', 'nav', 'footer', 'header', 'aside']):
                tag.decompose()
            main = soup.find('main') or soup.find('article') or soup.find('div', class_=re.compile('content|main'))
            text = main.get_text(separator='\n', strip=True) if main else soup.get_text(separator='\n', strip=True)
            return (text, None) if text and len(text) > 200 else (None, "Insufficient text")
        except Exception as e:
            return None, str(e)


class NadaciaHandler(SourceHandler):
    """Handler for nadaciaeset.sk and nadacianbs.sk (nadácie/foundations).
    
    Structure: No attachments. Scrapes call_url pages.
    """
    
    def detect(self, urls: List[str]) -> bool:
        return any(x in u.lower() for u in urls for x in ['nadaciaeset', 'nadacianbs'])
    
    def classify_documents(self, urls: List[str]) -> List[DocumentInfo]:
        return [DocumentInfo(url, url.split('/')[-1], 'main', 1) for url in urls]
    
    def download_and_extract(self, url: str) -> Tuple[Optional[str], Optional[str]]:
        """Scrape nadácia web pages."""
        try:
            headers = {"User-Agent": "Mozilla/5.0"}
            r = requests.get(url, headers=headers, timeout=60)
            if r.status_code != 200:
                return None, f"HTTP {r.status_code}"
            
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(r.content, 'html.parser')
            for tag in soup(['script', 'style', 'nav', 'footer', 'header', 'aside']):
                tag.decompose()
            main = soup.find('main') or soup.find('article') or soup.find('div', class_=re.compile('content|main'))
            text = main.get_text(separator='\n', strip=True) if main else soup.get_text(separator='\n', strip=True)
            return (text, None) if text and len(text) > 100 else (None, "Insufficient text")
        except Exception as e:
            return None, str(e)


class CultureGovHandler(SourceHandler):
    """Handler for culture.gov.sk (Ministerstvo kultúry SR).
    
    Structure: PDF výzvy on culture.gov.sk/wp-content/uploads/
    Each podprogram has its own PDF with full call details.
    Skip: formuláre, GDPR, manuály, avíza, vzory, čestné vyhlásenia.
    """
    
    def detect(self, urls: List[str]) -> bool:
        return any('culture.gov.sk' in u.lower() for u in urls)
    
    def classify_documents(self, urls: List[str]) -> List[DocumentInfo]:
        docs = []
        for url in urls:
            fname = url.split('/')[-1].lower()
            if any(x in fname for x in ['vyzva', 'výzva']):
                docs.append(DocumentInfo(url, fname, 'main', 1))
            elif any(x in fname for x in ['hodnotiace', 'kriteria']):
                docs.append(DocumentInfo(url, fname, 'criteria', 2))
            elif any(x in fname for x in ['prirucka', 'navod', 'pokyny']):
                docs.append(DocumentInfo(url, fname, 'conditions', 3))
            elif any(x in fname for x in ['avizo', 'suhlas', 'stanovisko', 'splnomocnenie',
                     'vyhlasenie', 'manual', 'kontakty', 'komisi', 'formulár', 'vyuctovan']):
                docs.append(DocumentInfo(url, fname, 'skip', 0))
            elif fname.endswith('.pdf'):
                docs.append(DocumentInfo(url, fname, 'other', 5))
        return sorted([d for d in docs if d.doc_type != 'skip'], key=lambda x: x.priority)

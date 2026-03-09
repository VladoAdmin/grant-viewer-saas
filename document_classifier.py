#!/usr/bin/env python3
"""Document type classifier for grant attachments.

Determines whether a document should be chunked based on:
1. Filename patterns
2. Content analysis
3. File size/heuristics
"""

import re
from typing import Tuple, Optional
from dataclasses import dataclass
from enum import Enum


class DocType(Enum):
    """Document classification types."""
    KEY = "key"           # Definitely chunk (conditions, guide, criteria)
    SUPPORTING = "supporting"  # Probably chunk (lists, specifications)
    FORM = "form"         # Don't chunk (application forms)
    TECHNICAL = "technical"  # Don't chunk (manuals, GDPR)
    UNKNOWN = "unknown"   # Default - use heuristics


@dataclass
class DocClassification:
    doc_type: DocType
    confidence: float  # 0.0 - 1.0
    reason: str
    should_chunk: bool


class DocumentClassifier:
    """Classify grant documents for embedding decisions."""
    
    # Patterns that indicate document type from filename
    SKIP_PATTERNS = [
        # Forms and applications
        r'formular',
        r'ziadost',
        r'formul[áa]r',
        r'žiadost',
        r'application',
        r'vyplnenie',  # Instructions for filling
        r'vzor',  # Templates
        
        # Technical/portal
        r'pouzivatelsky[_-]?manual',
        r'manual[_-]?pouzivatela',
        r'user[_-]?manual',
        r'portal',
        r'navod[_-]?na[_-]?pouzitie',
        r'informacie[_-]?gdpr',
        r'gdpr[_-]?inform',
        r'osobne[_-]?udaje',
        
        # Tests and administrative
        r'test[_-]?podniku',
        r'podnik[_-]?v[_-]?tazkostiach',
        r'dnsh',  # Do Not Significant Harm (often technical checklist)
        
        # Just forms
        r'priloha[_-]?c\._?1[_-]?formular',  # Form attachment #1
        r'priloha[_-]?1[_-]?formular',
    ]
    
    KEY_PATTERNS = [
        # Main documents
        r'vyzva',  # The call itself
        r'prirucka[_-]?pre[_-]?ziadatela',
        r'priručk[aa].*žiada',
        r'podmienky',
        r'crit[ée]ria',  # criteria
        r'hodnotiace[_-]?kriteria',
        r'zoznam[_-]?opravnenych',
        r'opravneni[_-]?ziadatelia',
        r'specifikacia',
        r'v[ýy]zva.*program',  # Call from program
        r'usmernenie',
        r'metodika',
    ]
    
    # Content indicators (first 1000 chars)
    CONTENT_KEY_INDICATORS = [
        'podmienky poskytnutia',
        'oprávnený žiadateľ',
        'oprávnené náklady',
        'hodnotiace kritériá',
        'predmet podpory',
        'cieľová skupina',
        'alokácia',
        'výzva z programu',
        'identifikácia výzvy',
        'špecifický cieľ',
        'opatrenie',
        'kritériá pre výber',
        'monitoring a hodnotenie',
    ]
    
    CONTENT_SKIP_INDICATORS = [
        'používateľský manuál',
        'návod na použitie',
        'prihlásenie do portálu',
        'prihláste sa do',
        'gdpr',
        'ochrana osobných údajov',
        'formulár žiadosti',
        'žiadosti o nenávratný finančný príspevok',  # The form itself
        'vyplňte všetky povinné polia',
        'povinné polia označené',
        'test podniku v ťažkostiach',
        'kontrolný zoznam',
        'checklist',
        'inštrukcia k vyplneniu formulára',
        'návod na vyplnenie',
        'pokyny k podávaniu žiadosti',  # Instructions for submitting
    ]
    
    # High-confidence skip patterns (if found, immediately skip)
    STRONG_SKIP_PATTERNS = [
        'formulár žiadosti',
        'žiadosti o nenávratný finančný príspevok',
        'kontrolný zoznam žiadosti',
        'inštrukcia k vyplneniu',
        'používateľský manuál',
    ]
    
    def classify_by_filename(self, filename: str) -> Optional[DocClassification]:
        """Classify based on filename only."""
        filename_lower = filename.lower()
        
        # Check skip patterns first
        for pattern in self.SKIP_PATTERNS:
            if re.search(pattern, filename_lower):
                return DocClassification(
                    doc_type=DocType.FORM if 'form' in pattern or 'ziad' in pattern else DocType.TECHNICAL,
                    confidence=0.85,
                    reason=f"Filename matches pattern: {pattern}",
                    should_chunk=False
                )
        
        # Check key patterns
        for pattern in self.KEY_PATTERNS:
            if re.search(pattern, filename_lower):
                return DocClassification(
                    doc_type=DocType.KEY,
                    confidence=0.80,
                    reason=f"Filename matches key pattern: {pattern}",
                    should_chunk=True
                )
        
        return None
    
    def classify_by_content(self, text: str, filename: str = "") -> DocClassification:
        """Classify based on document content."""
        text_lower = text[:3000].lower()  # First 3000 chars for better analysis
        filename_lower = filename.lower()
        
        # Check strong skip patterns first (immediate decision)
        for pattern in self.STRONG_SKIP_PATTERNS:
            if pattern in text_lower:
                return DocClassification(
                    doc_type=DocType.FORM,
                    confidence=0.90,
                    reason=f"Strong skip pattern found: '{pattern}'",
                    should_chunk=False
                )
        
        # Count indicators
        key_score = sum(1 for ind in self.CONTENT_KEY_INDICATORS if ind in text_lower)
        skip_score = sum(1 for ind in self.CONTENT_SKIP_INDICATORS if ind in text_lower)
        
        # Check for form-like structures (checkboxes, input fields)
        form_structures = [
            text_lower.count('□'),  # Empty checkbox
            text_lower.count('☐'),  # Empty checkbox variant
            text_lower.count('[ ]'),  # Empty field
            text_lower.count('( )'),  # Radio button
        ]
        form_score = sum(1 for x in form_structures if x > 3)  # Multiple fields
        
        # If it looks like a form
        if form_score >= 2 or 'formulár' in text_lower[:500]:
            return DocClassification(
                doc_type=DocType.FORM,
                confidence=0.75,
                reason=f"Form-like structure detected (fields={sum(form_structures)})",
                should_chunk=False
            )
        
        # Compare key vs skip indicators
        if skip_score > key_score and skip_score >= 2:
            return DocClassification(
                doc_type=DocType.TECHNICAL,
                confidence=min(0.6 + skip_score * 0.1, 0.85),
                reason=f"Content indicators: skip={skip_score}, key={key_score}",
                should_chunk=False
            )
        elif key_score > skip_score or key_score >= 3:
            return DocClassification(
                doc_type=DocType.KEY,
                confidence=min(0.6 + key_score * 0.1, 0.85),
                reason=f"Content indicators: key={key_score}, skip={skip_score}",
                should_chunk=True
            )
        
        # For UUID-named files with no clear indicators, try AI classification
        if self._looks_like_uuid(filename_lower):
            if text and len(text) > 500:
                ai_result = self._get_ai_classifier().classify(text, filename)
                if ai_result:
                    return DocClassification(
                        doc_type=DocType(ai_result.doc_type) if ai_result.doc_type in ["key", "form", "technical", "unknown"] else DocType.UNKNOWN,
                        confidence=ai_result.confidence,
                        reason=f"AI classified: {ai_result.reasoning}",
                        should_chunk=ai_result.should_chunk
                    )
            
            # Fallback: skip UUID files if AI fails
            return DocClassification(
                doc_type=DocType.UNKNOWN,
                confidence=0.6,
                reason="UUID filename, AI unavailable - conservative skip",
                should_chunk=False
            )
        
        return DocClassification(
            doc_type=DocType.UNKNOWN,
            confidence=0.5,
            reason="No clear indicators in content",
            should_chunk=True  # Only chunk unknown if not UUID
        )
    
    def _looks_like_uuid(self, filename: str) -> bool:
        """Check if filename looks like a UUID."""
        import re
        # Match UUID pattern: 8-4-4-4-12 hex characters
        uuid_pattern = r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}'
        return bool(re.match(uuid_pattern, filename))
    
    def __init__(self):
        self.ai_classifier = None  # Lazy load
    
    def _get_ai_classifier(self):
        """Lazy load AI classifier."""
        if self.ai_classifier is None:
            from ai_classifier import AIClassifier
            self.ai_classifier = AIClassifier()
        return self.ai_classifier

    def classify(self, filename: str, text: Optional[str] = None) -> DocClassification:
        """
        Full classification pipeline.
        
        Priority:
        1. Filename patterns (strong indicators)
        2. Content analysis (critical for UUID-named files)
        3. Default based on filename type
        """
        # Try filename first (high confidence only)
        filename_result = self.classify_by_filename(filename)
        if filename_result and filename_result.confidence >= 0.85:
            return filename_result
        
        # Try content analysis (very important for UUID-named files)
        if text:
            content_result = self.classify_by_content(text, filename)
            
            # High confidence content result wins
            if content_result.confidence >= 0.75:
                return content_result
            
            # Combine results if we have both
            if filename_result:
                # Both methods agree
                if filename_result.should_chunk == content_result.should_chunk:
                    return DocClassification(
                        doc_type=filename_result.doc_type,
                        confidence=max(filename_result.confidence, content_result.confidence),
                        reason=f"Filename: {filename_result.reason}; Content: {content_result.reason}",
                        should_chunk=filename_result.should_chunk
                    )
                # Disagreement - use content for UUID files, filename for others
                if self._looks_like_uuid(filename.lower()):
                    return DocClassification(
                        doc_type=content_result.doc_type,
                        confidence=content_result.confidence,
                        reason=f"UUID file, using content: {content_result.reason}",
                        should_chunk=content_result.should_chunk
                    )
                else:
                    return DocClassification(
                        doc_type=filename_result.doc_type,
                        confidence=filename_result.confidence,
                        reason=f"Using filename over content: {filename_result.reason}",
                        should_chunk=filename_result.should_chunk
                    )
            
            return content_result
        
        # Fallback to filename result
        if filename_result:
            return filename_result
        
        # Default: skip UUID files, chunk others
        should_chunk = not self._looks_like_uuid(filename.lower())
        return DocClassification(
            doc_type=DocType.UNKNOWN,
            confidence=0.5,
            reason="No classification possible" + (" (UUID - skipped)" if not should_chunk else ""),
            should_chunk=should_chunk
        )


def test_classifier():
    """Test the classifier with sample filenames."""
    classifier = DocumentClassifier()
    
    test_cases = [
        # (filename, expected_should_chunk, description)
        ("Priloha-c.-1-Prirucka-pre-ziadatela-I.pdf", True, "Guide for applicants"),
        ("Priloha-c.-2-Hodnotiace-kriteria.pdf", True, "Evaluation criteria"),
        ("Pouzivatelsky-manual.pdf", False, "User manual"),
        ("Informacie_GDPR_EF.pdf", False, "GDPR info"),
        ("Priloha-1-Formular-ZoNFP.pdf", False, "Application form"),
        ("Vyzva-B-1-rok-2026.pdf", True, "The call itself"),
        ("Zoznam-opravnenych-ziadatelov.pdf", True, "List of eligible applicants"),
        ("Test-podniku-v-tazkostiach.pdf", False, "Enterprise test"),
        ("Priloha-3-DNSH.pdf", False, "Do No Significant Harm (technical)"),
        ("Metodika-hodnotenia.pdf", True, "Evaluation methodology"),
    ]
    
    print("="*70)
    print("DOCUMENT CLASSIFIER TEST")
    print("="*70)
    
    correct = 0
    for filename, expected, description in test_cases:
        result = classifier.classify(filename)
        status = "✅" if result.should_chunk == expected else "❌"
        if result.should_chunk == expected:
            correct += 1
        
        print(f"\n{status} {description}")
        print(f"   File: {filename}")
        print(f"   Type: {result.doc_type.value}, Chunk: {result.should_chunk}")
        print(f"   Confidence: {result.confidence:.2f}")
        print(f"   Reason: {result.reason}")
    
    print(f"\n{'='*70}")
    print(f"Accuracy: {correct}/{len(test_cases)} ({100*correct/len(test_cases):.0f}%)")
    print("="*70)


if __name__ == "__main__":
    test_classifier()

"""Tests for extractor and classifier (TASK-004, TASK-005)."""

import pytest
from scraper.extractor.classifier import classify_document
from scraper.extractor.pdf_extractor import extract_text_from_bytes
from scraper.extractor.zip_handler import download_content, extract_from_url


class TestClassifier:
    """Tests for document classifier (TASK-004)."""

    def test_classify_main_by_filename(self):
        """Classifies main documents by filename."""
        doc_type, conf = classify_document("Vyzva-PSK-001-2024.pdf")
        assert doc_type == "main"
        assert conf > 0.3

    def test_classify_conditions_by_filename(self):
        """Classifies conditions documents."""
        doc_type, conf = classify_document("Prirucka-pre-ziadatelov.pdf")
        assert doc_type == "conditions"
        assert conf > 0.2

    def test_classify_criteria_by_filename(self):
        """Classifies criteria documents."""
        doc_type, conf = classify_document("Hodnotiace-kriteria-priloha-c-2.pdf")
        assert doc_type == "criteria"
        assert conf > 0.2

    def test_classify_skip_by_filename(self):
        """Classifies skip documents."""
        doc_type, _ = classify_document("Formular-ziadosti-GDPR.pdf")
        assert doc_type == "skip"

    def test_classify_by_content(self):
        """Classifies by content when filename is ambiguous."""
        text = "Výzva na predkladanie žiadostí. Cieľ výzvy je podporiť oprávnené aktivity."
        doc_type, conf = classify_document("document_123.pdf", text)
        assert doc_type == "main"

    def test_classify_empty(self):
        """Handles empty inputs gracefully."""
        doc_type, conf = classify_document("unknown.pdf", "")
        assert doc_type in ("unknown", "main")
        assert conf < 0.5

    def test_classify_costs_document(self):
        """Classifies cost-related documents."""
        doc_type, conf = classify_document("Opravnene-naklady-a-vydavky.pdf",
                                           "Oprávnené náklady zahŕňajú výdavky na rozpočet")
        assert doc_type == "costs"

    def test_all_types_distinguishable(self):
        """Different document types produce different classifications."""
        results = {
            classify_document("Vyzva-hlavna.pdf", "Výzva na oprávnené aktivity a alokácia")[0],
            classify_document("Prirucka-podmienky.pdf", "Podmienky oprávnenosti a oprávnený žiadateľ")[0],
            classify_document("Hodnotiace-kriteria.pdf", "Hodnotiace kritériá a bodové hodnotenie")[0],
            classify_document("Formular-GDPR.pdf", "Formulár na vyplnenie")[0],
        }
        # At least 3 different types
        assert len(results) >= 3


class TestPDFExtractor:
    """Tests for PDF extraction (TASK-004)."""

    def test_extract_from_real_url(self):
        """Download and extract a real ITMS21 PDF."""
        # Use a known ITMS21 document URL
        content, ct = download_content(
            "https://api.itms21.sk/public/v1/dokument/id/1",
            timeout=15
        )
        # Don't fail if API is down, just skip
        if content is None:
            pytest.skip("ITMS21 API not reachable")
        if content[:5] != b"%PDF-":
            pytest.skip("Response is not a PDF")

        text = extract_text_from_bytes(content)
        if text is None:
            pytest.skip("PDF has no extractable text")
        assert len(text) > 100

    def test_extract_empty_bytes(self):
        """Handles empty bytes gracefully."""
        result = extract_text_from_bytes(b"")
        assert result is None

    def test_extract_invalid_bytes(self):
        """Handles invalid PDF gracefully."""
        result = extract_text_from_bytes(b"not a pdf file content")
        assert result is None


class TestChunker:
    """Tests for text chunking (TASK-005)."""

    def test_chunk_basic(self):
        """Chunks a basic document."""
        from scraper.embedder.chunker import chunk_document, count_tokens

        text = "Paragraph one about grant conditions.\n\n" * 50
        chunks = chunk_document(text, "Test Call", "test.pdf", "main")

        assert len(chunks) > 0
        for chunk in chunks:
            assert chunk.text  # Has content
            assert chunk.call_title == "Test Call"
            assert chunk.doc_type == "main"
            assert "[Výzva:" in chunk.text  # Has context prefix
            assert chunk.token_count > 0

    def test_chunk_size_bounds(self):
        """Chunks are within size bounds."""
        from scraper.embedder.chunker import chunk_document, count_tokens, CHUNK_MAX_TOKENS

        text = "This is a test sentence about grant eligibility criteria. " * 200
        chunks = chunk_document(text, "Test", "test.pdf")

        for chunk in chunks:
            # Token count should not wildly exceed max (some overhead for prefix)
            assert chunk.token_count < CHUNK_MAX_TOKENS * 2, \
                f"Chunk too large: {chunk.token_count} tokens"

    def test_chunk_empty_text(self):
        """Handles empty text."""
        from scraper.embedder.chunker import chunk_document
        chunks = chunk_document("", "Test", "test.pdf")
        assert len(chunks) == 0

    def test_chunk_short_text(self):
        """Short text produces single chunk."""
        from scraper.embedder.chunker import chunk_document
        chunks = chunk_document("Short text here.", "Test", "test.pdf")
        assert len(chunks) == 1

    def test_context_prefix(self):
        """Chunks have correct context prefix."""
        from scraper.embedder.chunker import chunk_document
        text = "Some grant document content about eligible applicants.\n\n" * 10
        chunks = chunk_document(text, "My Grant Call", "priloha.pdf", "conditions")

        assert len(chunks) > 0
        for chunk in chunks:
            assert "My Grant Call" in chunk.text
            assert "priloha.pdf" in chunk.text
            assert "conditions" in chunk.text

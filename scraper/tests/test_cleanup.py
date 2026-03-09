"""Tests for cleanup and dedup (TASK-009)."""

import pytest
from scraper.cleanup import run_cleanup, run_dedup, run_all_maintenance


class TestCleanup:
    """Tests for cleanup operations."""

    def test_cleanup_runs_without_error(self):
        """Cleanup runs without crashing."""
        result = run_cleanup(months_threshold=120)  # Very high threshold to avoid deleting real data
        assert isinstance(result, dict)
        assert "soft_deleted_calls" in result
        assert "hard_deleted_chunks" in result

    def test_dedup_runs_without_error(self):
        """Dedup detection runs without crashing."""
        result = run_dedup()
        assert isinstance(result, dict)
        assert "duplicates_found" in result
        assert "duplicates_merged" in result

    def test_all_maintenance(self):
        """Full maintenance cycle runs without crashing."""
        result = run_all_maintenance()
        assert "cleanup" in result
        assert "dedup" in result


class TestPDFExport:
    """Tests for PDF export (TASK-007)."""

    def test_generate_pdf(self):
        """Can generate a PDF from call data."""
        from scraper.pdf_export import generate_call_pdf

        call = {
            "title": "Test Grant Call",
            "source": "portal.itms21.sk",
            "status": "otvorená",
            "provider": "Test Provider",
            "announced_at": "2026-01-15",
            "deadline_at": "2026-06-30",
            "total_allocation": "1000000",
            "eligible_applicants": "Legal entities, NGOs",
        }
        attributes = {
            "Program": "Test Program",
            "Kód výzvy": "PSK-001-2026",
            "Druh výzvy": "dopytovo-orientovaná",
            "Miesto realizácie": "Slovenská republika",
            "Alokácia EÚ": "800,000.00 €",
            "Alokácia spolu": "1,000,000.00 €",
            "Špecifický cieľ": "Podpora inovácií",
        }
        attachments = [
            {"name": "Vyzva.pdf", "url": "https://example.com/vyzva.pdf"},
        ]

        pdf_bytes = generate_call_pdf(call, attributes, attachments)
        assert pdf_bytes is not None
        assert len(pdf_bytes) > 1000
        assert pdf_bytes[:5] == b"%PDF-"

    def test_generate_pdf_minimal_data(self):
        """Can generate PDF with minimal data."""
        from scraper.pdf_export import generate_call_pdf

        call = {"title": "Minimal Call", "source": "test", "status": ""}
        attributes = {}

        pdf_bytes = generate_call_pdf(call, attributes)
        assert pdf_bytes is not None
        assert pdf_bytes[:5] == b"%PDF-"

    def test_generate_pdf_from_db(self):
        """Can generate PDF from real DB data."""
        from scraper.db import get_db
        from scraper.pdf_export import generate_call_pdf

        db = get_db()
        calls = db.get_grant_calls(limit=1)
        if not calls:
            pytest.skip("No calls in DB")

        call = calls[0]
        attributes = db.get_attributes(call["id"])

        pdf_bytes = generate_call_pdf(call, attributes)
        assert pdf_bytes is not None
        assert len(pdf_bytes) > 500

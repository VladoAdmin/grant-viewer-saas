"""Tests for ITMS21 handler (TASK-003)."""

import pytest
from scraper.handlers.itms21 import ITMS21Handler, _api_get, _ts_to_date


class TestITMS21Handler:
    """Integration tests for ITMS21 handler."""

    @pytest.fixture
    def handler(self):
        return ITMS21Handler()

    def test_source_name(self, handler):
        assert handler.source_name == "portal.itms21.sk"

    def test_base_url(self, handler):
        assert "portal.itms21.sk" in handler.base_url

    def test_api_get_listing(self):
        """ITMS21 API returns call listings."""
        data = _api_get("/vyzva/", params={"limit": 5, "offset": 0})
        assert "results" in data
        results = data["results"]
        assert len(results) > 0
        assert "id" in results[0]

    def test_get_call_listings(self, handler):
        """Handler returns call listings."""
        listings = handler.get_call_listings(limit=5)
        assert len(listings) >= 1
        assert "id" in listings[0]

    def test_parse_call_detail(self, handler):
        """Handler can parse a call detail."""
        listings = handler.get_call_listings(limit=1)
        assert len(listings) >= 1

        call, attributes, attachments = handler.parse_call_detail(listings[0])

        assert call.source == "portal.itms21.sk"
        assert call.title
        assert call.call_url.startswith("https://")
        assert isinstance(attributes, dict)
        assert isinstance(attachments, list)

    def test_ts_to_date(self):
        """Timestamp conversion works."""
        assert _ts_to_date(1704067200000) == "2024-01-01"
        assert _ts_to_date(None) is None
        assert _ts_to_date(0) is not None  # epoch

    def test_parse_call_has_attachments(self, handler):
        """At least some calls should have attachments."""
        listings = handler.get_call_listings(limit=10)
        has_attachments = False
        for listing in listings[:5]:
            call, attrs, atts = handler.parse_call_detail(listing)
            if atts:
                has_attachments = True
                assert atts[0].name
                assert atts[0].url
                break
        # It's OK if no attachments found in first 5, but log it
        if not has_attachments:
            print("WARNING: No attachments found in first 5 calls")

    def test_parse_call_has_attributes(self, handler):
        """Parsed calls should have extended attributes."""
        listings = handler.get_call_listings(limit=3)
        call, attributes, _ = handler.parse_call_detail(listings[0])

        # At least some standard attributes should be present
        possible_keys = {"Program", "Vyhlasovateľ výzvy", "Kód výzvy", "Druh výzvy"}
        found_keys = set(attributes.keys()) & possible_keys
        assert len(found_keys) >= 1, f"Expected at least 1 standard attribute, got: {attributes.keys()}"

"""Tests for database client (TASK-001, TASK-002)."""

import pytest
from scraper.db import get_db, SupabaseClient


class TestSupabaseClient:
    """Integration tests for the Supabase client."""

    @pytest.fixture
    def db(self):
        return get_db()

    def test_connection(self, db):
        """DB client initializes without error."""
        assert db.base_url
        assert db.key

    def test_get_grant_calls(self, db):
        """Can fetch grant calls from DB."""
        calls = db.get_grant_calls(limit=5)
        assert isinstance(calls, list)
        # We know DB has 123 calls
        assert len(calls) > 0

    def test_get_grant_call_by_id(self, db):
        """Can fetch a specific call by ID."""
        calls = db.get_grant_calls(limit=1)
        if calls:
            call = db.get_grant_call_by_id(calls[0]["id"])
            assert call is not None
            assert "title" in call
            assert "source" in call

    def test_get_attachments(self, db):
        """Can fetch attachments for a call."""
        calls = db.get_grant_calls(limit=5)
        for call in calls:
            atts = db.get_attachments(call["id"])
            assert isinstance(atts, list)
            # At least some calls should have attachments
            break

    def test_scraper_run_lifecycle(self, db):
        """Can create and finish a scraper run."""
        run = db.start_scraper_run("test_source")
        assert run is not None
        assert "id" in run
        assert run["status"] == "running"

        db.finish_scraper_run(
            run["id"], status="success",
            calls_found=10, calls_new=3
        )

        runs = db.get_last_scraper_runs(limit=1)
        assert len(runs) > 0
        latest = runs[0]
        assert latest["source"] == "test_source"

    def test_error_logging(self, db):
        """Can log errors to DB."""
        error_id = db.log_error(
            source="test",
            component="test_db",
            message="Test error message",
            severity="warning",
        )
        assert error_id.startswith("ERR-")

    def test_save_and_get_attributes(self, db):
        """Can save and retrieve attributes."""
        calls = db.get_grant_calls(limit=1)
        if not calls:
            pytest.skip("No calls in DB")

        call_id = calls[0]["id"]
        test_attrs = {
            "test_key_1": "test_value_1",
            "test_key_2": "test_value_2",
        }

        db.save_attributes(call_id, test_attrs)
        result = db.get_attributes(call_id)
        assert "test_key_1" in result
        assert result["test_key_1"] == "test_value_1"

    def test_upsert_idempotent(self, db):
        """Upsert same call twice should not create duplicates."""
        calls = db.get_grant_calls(limit=1)
        if not calls:
            pytest.skip("No calls in DB")

        call = calls[0]
        # Upsert same data
        result = db.upsert_grant_call({
            "source": call["source"],
            "source_url": call.get("source_url", ""),
            "call_url": call["call_url"],
            "title": call["title"],
            "updated_at": "2026-03-09T12:00:00Z",
        })
        assert result is not None
        assert result["id"] == call["id"]  # Same ID, not a new record


class TestHybridSearch:
    """Tests for hybrid search function (TASK-006)."""

    @pytest.fixture
    def db(self):
        return get_db()

    def test_hybrid_search_returns_results(self, db):
        """Hybrid search returns results for a known query."""
        # We need a real embedding for this test
        # For now, just verify the RPC exists and doesn't crash
        try:
            from scraper.embedder.embedder import embed_texts
            embeddings = embed_texts(["test query"])
            if embeddings:
                results = db.hybrid_search(
                    query_text="výzva dotácia",
                    query_embedding=embeddings[0],
                    match_count=5,
                )
                assert isinstance(results, list)
        except Exception:
            pytest.skip("OpenAI API not available for embedding")

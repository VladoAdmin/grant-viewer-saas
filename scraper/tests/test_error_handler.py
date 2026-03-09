"""Tests for error handling (TASK-008)."""

import pytest
from scraper.error_handler import (
    ErrorCollector, ScraperError, graceful, log_error, safe_execute
)


class TestErrorHandler:
    """Tests for error handling system."""

    def test_log_error_returns_id(self):
        """log_error returns an error ID."""
        error_id = log_error("test", "test_component", "Test error message")
        assert error_id.startswith("ERR-")

    def test_safe_execute_success(self):
        """safe_execute returns function result on success."""
        result = safe_execute(lambda: 42, component="test")
        assert result == 42

    def test_safe_execute_failure(self):
        """safe_execute returns default on error."""
        def failing_func():
            raise ValueError("boom")

        result = safe_execute(failing_func, component="test", default="fallback")
        assert result == "fallback"

    def test_graceful_decorator_success(self):
        """@graceful decorator passes through on success."""
        @graceful(component="test", default=[])
        def good_func():
            return [1, 2, 3]

        result = good_func()
        assert result == [1, 2, 3]

    def test_graceful_decorator_failure(self):
        """@graceful decorator returns default on failure."""
        @graceful(component="test", default="default_value")
        def bad_func():
            raise RuntimeError("crash")

        result = bad_func()
        assert result == "default_value"

    def test_error_collector_catches(self):
        """ErrorCollector catches exceptions without propagating."""
        collector = ErrorCollector("test")

        with collector.catch(component="sub_module"):
            raise ValueError("test error")

        # Should not raise
        assert collector.has_errors
        assert len(collector.errors) == 1

    def test_error_collector_no_errors(self):
        """ErrorCollector with no errors."""
        collector = ErrorCollector("test")

        with collector.catch(component="ok_module"):
            result = 1 + 1  # No error

        assert not collector.has_errors

    def test_error_collector_summary(self):
        """ErrorCollector provides summary."""
        collector = ErrorCollector("test")

        for i in range(3):
            with collector.catch(component=f"module_{i}"):
                raise ValueError(f"error {i}")

        summary = collector.summary()
        assert summary["total_errors"] == 3
        assert summary["total_warnings"] == 0

    def test_error_collector_warnings(self):
        """ErrorCollector tracks warnings."""
        collector = ErrorCollector("test")
        collector.add_warning("comp", "This is a warning")

        assert not collector.has_errors  # Warnings don't count as errors
        summary = collector.summary()
        assert summary["total_warnings"] == 1

    def test_scraper_error(self):
        """ScraperError has correct attributes."""
        err = ScraperError("test message", component="itms21", severity="critical")
        assert err.message == "test message"
        assert err.component == "itms21"
        assert err.severity == "critical"

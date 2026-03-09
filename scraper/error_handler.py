"""Centralized error handling for the scraper.

Requirements from PRD (OP-003):
- System must not crash during scraping/embedding/extraction
- Errors logged with error_id
- User gets standard error message with error_id
- Admin notified about errors

This module provides decorators and utilities for graceful error handling.
"""

import functools
import logging
import traceback
from typing import Any, Callable, Optional, TypeVar

from .db import get_db

log = logging.getLogger(__name__)

T = TypeVar("T")


class ScraperError(Exception):
    """Base exception for scraper errors with error_id tracking."""

    def __init__(self, message: str, error_id: Optional[str] = None,
                 component: str = "unknown", severity: str = "error"):
        self.message = message
        self.error_id = error_id
        self.component = component
        self.severity = severity
        super().__init__(message)


def log_error(source: str, component: str, message: str,
              severity: str = "error", call_id: Optional[int] = None,
              details: Optional[dict] = None) -> str:
    """Log an error to DB and return error_id.

    Always succeeds (catches its own exceptions to prevent cascade failures).
    """
    try:
        db = get_db()
        error_id = db.log_error(
            source=source,
            component=component,
            message=message,
            severity=severity,
            call_id=call_id,
            details=details,
        )
        log.error(f"[{error_id}] [{component}] {message}")
        return error_id
    except Exception as e:
        # If even error logging fails, at least log to file
        log.critical(f"Error logging failed: {e}. Original error: [{component}] {message}")
        return "ERR-LOGGING-FAILED"


def safe_execute(func: Callable[..., T], *args,
                 component: str = "unknown",
                 default: Any = None,
                 call_id: Optional[int] = None,
                 **kwargs) -> Any:
    """Execute a function with error handling. Never raises.

    Returns the function result or default value on error.
    """
    try:
        return func(*args, **kwargs)
    except Exception as e:
        error_id = log_error(
            source="scraper",
            component=component,
            message=f"{func.__name__} failed: {str(e)[:500]}",
            severity="error",
            call_id=call_id,
            details={"traceback": traceback.format_exc()[:2000]},
        )
        return default


def graceful(component: str = "unknown", default: Any = None):
    """Decorator for graceful error handling.

    Usage:
        @graceful(component="itms21", default=[])
        def fetch_calls():
            ...
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                error_id = log_error(
                    source="scraper",
                    component=component,
                    message=f"{func.__name__} failed: {str(e)[:500]}",
                    severity="error",
                    details={"traceback": traceback.format_exc()[:2000]},
                )
                log.error(f"[{error_id}] Graceful fallback to default: {default}")
                return default
        return wrapper
    return decorator


class ErrorCollector:
    """Collects errors during a pipeline run without stopping execution.

    Usage:
        collector = ErrorCollector("scraper")
        for call in calls:
            with collector.catch(call_id=call.id):
                process(call)
        report = collector.summary()
    """

    def __init__(self, source: str = "scraper"):
        self.source = source
        self.errors: list = []
        self.warnings: list = []

    def catch(self, component: str = "unknown", call_id: Optional[int] = None):
        """Context manager that catches and logs errors."""
        return _ErrorContext(self, component, call_id)

    def add_error(self, component: str, message: str, call_id: Optional[int] = None):
        """Manually add an error."""
        error_id = log_error(self.source, component, message, call_id=call_id)
        self.errors.append({"error_id": error_id, "component": component, "message": message})

    def add_warning(self, component: str, message: str):
        """Add a warning (not logged to DB)."""
        log.warning(f"[{component}] {message}")
        self.warnings.append({"component": component, "message": message})

    @property
    def has_errors(self) -> bool:
        return len(self.errors) > 0

    def summary(self) -> dict:
        """Generate error summary."""
        return {
            "total_errors": len(self.errors),
            "total_warnings": len(self.warnings),
            "errors": self.errors[-10:],  # Last 10
            "warnings": self.warnings[-10:],
        }


class _ErrorContext:
    """Context manager for ErrorCollector."""

    def __init__(self, collector: ErrorCollector, component: str, call_id: Optional[int]):
        self.collector = collector
        self.component = component
        self.call_id = call_id

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type is not None:
            error_id = log_error(
                source=self.collector.source,
                component=self.component,
                message=str(exc_val)[:500],
                call_id=self.call_id,
                details={"traceback": traceback.format_exc()[:2000]},
            )
            self.collector.errors.append({
                "error_id": error_id,
                "component": self.component,
                "message": str(exc_val)[:500],
            })
            return True  # Suppress the exception

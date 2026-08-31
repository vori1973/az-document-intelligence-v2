"""
Structured telemetry helpers for Application Insights.

Usage:
    from shared.telemetry import log_step_start, log_step_end, log_step_error, track_metric

All helpers emit both a structured log record (JSON) and an App Insights custom event.
"""

from __future__ import annotations

import logging
import os
import time
from contextlib import contextmanager
from typing import Any

if os.environ.get("APPLICATIONINSIGHTS_CONNECTION_STRING"):
    from azure.monitor.opentelemetry import configure_azure_monitor

    configure_azure_monitor(logger_name="pipeline")

logger = logging.getLogger("pipeline")
logger.setLevel(logging.INFO)


def _emit(event: str, props: dict[str, Any]) -> None:
    extra = {"custom_dimensions": props}
    logger.info(event, extra=extra)


def log_step_start(step: str, doc_id: str, run_id: str, **kwargs: Any) -> None:
    _emit(
        f"pipeline.step.start",
        {"step": step, "doc_id": doc_id, "run_id": run_id, **kwargs},
    )


def log_step_end(step: str, doc_id: str, run_id: str, duration_ms: float, **kwargs: Any) -> None:
    _emit(
        f"pipeline.step.end",
        {"step": step, "doc_id": doc_id, "run_id": run_id, "duration_ms": duration_ms, **kwargs},
    )


def log_step_error(step: str, doc_id: str, run_id: str, exc: Exception, **kwargs: Any) -> None:
    _emit(
        f"pipeline.step.error",
        {
            "step": step,
            "doc_id": doc_id,
            "run_id": run_id,
            "error": str(exc),
            "error_type": type(exc).__name__,
            **kwargs,
        },
    )
    logger.exception(f"[{step}] Error for doc_id={doc_id}", exc_info=exc)


def track_metric(name: str, value: float, **props: Any) -> None:
    _emit(f"pipeline.metric.{name}", {"value": value, **props})


@contextmanager
def timed_step(step: str, doc_id: str, run_id: str, **kwargs: Any):
    """Context manager that logs step start/end and records duration."""
    log_step_start(step, doc_id, run_id, **kwargs)
    t0 = time.monotonic()
    try:
        yield
        duration_ms = (time.monotonic() - t0) * 1000
        log_step_end(step, doc_id, run_id, duration_ms=duration_ms, **kwargs)
    except Exception as exc:
        log_step_error(step, doc_id, run_id, exc, **kwargs)
        raise

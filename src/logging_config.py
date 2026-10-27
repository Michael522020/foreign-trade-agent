"""JSON 日志。每条业务日志都带 lead_id 与 trace_id。"""

from __future__ import annotations

import logging
from contextvars import ContextVar
from uuid import uuid4

import structlog

_trace_id: ContextVar[str] = ContextVar("trace_id", default="")
_configured = False


def bind_trace(trace_id: str) -> None:
    if not trace_id.strip():
        raise ValueError("trace_id 不能为空")
    _trace_id.set(trace_id.strip())


def current_trace_id() -> str:
    bound = _trace_id.get()
    if bound:
        return bound
    return uuid4().hex


def configure_logging() -> None:
    global _configured
    if _configured:
        return
    structlog.configure(
        processors=[
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=False,
    )
    _configured = True

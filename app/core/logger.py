"""
Structured JSON logging for the whole app.

Every line is one JSON object (one log entry per line, tracebacks included), written to a
rotating `app.log` (read by GET /admin/logs) and to stdout (DigitalOcean runtime logs).

Context travels with the request: `request_id` is set by the HTTP middleware, and
`bind_log_context(order_id=..., store_id=...)` adds fields that every later log line in the
same request / task carries automatically — so one order's journey can be filtered end to end.

Structured events: `log_event(logger, "order.created", "Order created", order_id=..., total=...)`.
"""
import json
import logging
import os
from contextvars import ContextVar
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from typing import Any

# Set per request by the HTTP middleware ("-" outside a request: startup, background jobs).
request_id_var: ContextVar[str] = ContextVar("request_id", default="-")
# Extra fields (store_id, order_id, method, path…) attached to every log line in this context.
_log_context: ContextVar[dict[str, Any]] = ContextVar("log_context", default={})

LOG_FILE = os.getenv("LOG_FILE", "app.log")
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
LOG_MAX_BYTES = int(os.getenv("LOG_MAX_BYTES", str(20 * 1024 * 1024)))
LOG_BACKUP_COUNT = int(os.getenv("LOG_BACKUP_COUNT", "5"))

# Keys whose values must never reach the logs (matched case-insensitively, anywhere in nested data).
_SENSITIVE_KEYS = (
    "pin", "password", "passwd", "secret", "token", "salt", "app_key", "api_key",
    "authorization", "card_number", "cvv", "otp", "security_token", "access_token",
)
_STANDARD_FIELDS = ("timestamp", "level", "logger", "message", "request_id")


def _is_sensitive(key: str) -> bool:
    k = key.lower()
    return any(s == k or k.endswith(f"_{s}") or k.startswith(f"{s}_") for s in _SENSITIVE_KEYS)


def redact(value: Any, _depth: int = 0) -> Any:
    """Copy of `value` with sensitive keys masked (recursively, bounded depth)."""
    if _depth > 6:
        return value
    if isinstance(value, dict):
        return {
            k: ("***" if isinstance(k, str) and _is_sensitive(k) and v not in (None, "") else redact(v, _depth + 1))
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [redact(v, _depth + 1) for v in value[:50]]
    return value


def bind_log_context(**fields: Any) -> None:
    """Attach fields (e.g. order_id, store_id) to every later log line in this request/task."""
    clean = {k: v for k, v in fields.items() if v is not None and v != ""}
    if clean:
        _log_context.set({**_log_context.get(), **clean})


def reset_log_context() -> None:
    _log_context.set({})


def get_log_context() -> dict[str, Any]:
    return dict(_log_context.get())


def log_event(logger: logging.Logger, event: str, message: str, level: int = logging.INFO, **fields: Any) -> None:
    """One structured event line: `event` is a dotted name (order.created, payment.status_changed…)."""
    logger.log(level, message, extra={"extra_data": {"event": event, **fields}}, stacklevel=2)


def _utc_iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


class JSONFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        entry: dict[str, Any] = {
            "timestamp": _utc_iso(record.created),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": request_id_var.get(),
        }
        for k, v in _log_context.get().items():
            entry.setdefault(k, v)

        extra = getattr(record, "extra_data", None)
        if isinstance(extra, dict):
            for k, v in redact(extra).items():
                if k not in _STANDARD_FIELDS:
                    entry[k] = v

        if record.levelno >= logging.WARNING:
            entry["source"] = f"{record.module}.{record.funcName}:{record.lineno}"
        if record.exc_info and record.exc_info[0] is not None:
            entry["error_type"] = record.exc_info[0].__name__
            entry["error_message"] = str(record.exc_info[1])
            entry["stack_trace"] = self.formatException(record.exc_info)

        return json.dumps(entry, default=str, ensure_ascii=False)


def setup_logging() -> None:
    """Route every logger (app, uvicorn, libraries) through the JSON formatter."""
    root = logging.getLogger()
    root.setLevel(getattr(logging, LOG_LEVEL, logging.INFO))
    for handler in root.handlers[:]:
        root.removeHandler(handler)

    formatter = JSONFormatter()
    file_handler = RotatingFileHandler(
        LOG_FILE, maxBytes=LOG_MAX_BYTES, backupCount=LOG_BACKUP_COUNT, encoding="utf-8"
    )
    file_handler.setFormatter(formatter)
    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    root.addHandler(file_handler)
    root.addHandler(stream_handler)

    for name in ("uvicorn", "uvicorn.error", "fastapi"):
        lg = logging.getLogger(name)
        lg.handlers = []
        lg.propagate = True
    # The HTTP middleware logs one richer line per request; uvicorn's access line would duplicate it.
    access = logging.getLogger("uvicorn.access")
    access.handlers = []
    access.propagate = False
    # Chatty libraries: only their warnings and errors.
    for name in ("httpx", "httpx2", "httpcore", "sqlalchemy.engine", "asyncio", "multipart"):
        logging.getLogger(name).setLevel(logging.WARNING)

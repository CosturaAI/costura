"""Process logging for the API and the worker.

Production emits one JSON object per line, with `request_id` when a request set it.
Development and test keep a single human line. The request id is the incoming
`X-Request-ID` when it is a short token, otherwise a new UUID.
"""

import json
import logging
import re
from contextvars import ContextVar
from datetime import UTC, datetime
from uuid import uuid4

from costura.config import get_settings

request_id_var: ContextVar[str | None] = ContextVar("costura_request_id", default=None)

# Structured fields a call site passes through `extra=`; the JSON line carries each one set.
CONTEXT_FIELDS = ("run_id", "org_id", "provider", "step", "month", "status", "duration_seconds")

_REQUEST_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


def resolve_request_id(header: str | None) -> str:
    """Accept a caller-supplied id that cannot break a log line; otherwise mint one."""
    if header is not None and _REQUEST_ID.fullmatch(header.strip()):
        return header.strip()
    return uuid4().hex


class JsonFormatter(logging.Formatter):
    """One JSON object per record. `request_id` is omitted when no request set it."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "ts": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        request_id = request_id_var.get()
        if request_id:
            payload["request_id"] = request_id
        for name in CONTEXT_FIELDS:
            value = getattr(record, name, None)
            if value is not None:
                payload[name] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


class RequestContextFormatter(logging.Formatter):
    """Human line. Appends `request_id=` only while a request is in progress."""

    def format(self, record: logging.LogRecord) -> str:
        rendered = super().format(record)
        request_id = request_id_var.get()
        if request_id:
            return f"{rendered} request_id={request_id}"
        return rendered


def build_formatter() -> logging.Formatter:
    if get_settings().costura_env == "production":
        return JsonFormatter()
    return RequestContextFormatter("%(asctime)s %(name)s %(message)s")


def configure_logging() -> None:
    """Attach one handler to the `costura` logger. Safe to call more than once.

    Production does not propagate, so uvicorn's root handler does not print the same
    line twice. Development and test propagate, so a test capture on the root logger
    still sees the record.
    """
    logger = logging.getLogger("costura")
    logger.setLevel(get_settings().costura_log_level)
    logger.handlers.clear()
    handler = logging.StreamHandler()
    handler.setFormatter(build_formatter())
    logger.addHandler(handler)
    logger.propagate = get_settings().costura_env != "production"

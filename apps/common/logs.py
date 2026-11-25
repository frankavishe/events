"""Structured logging. Log ids only: never phones, message texts, OTPs or account numbers."""

import json
import logging
import re
import time
import uuid
from contextvars import ContextVar
from datetime import UTC, datetime
from urllib.parse import quote

from celery import current_task
from django.conf import settings
from django.db import transaction

request_id: ContextVar[str] = ContextVar("request_id", default="")

_VALID_ID = re.compile(r"[A-Za-z0-9._-]{1,64}")
_request_logger = logging.getLogger("apps.request")


def log_event(logger, event: str, **data) -> None:
    """Log a business event once the current transaction, if any, has committed."""
    message = " ".join([event, *(f"{key}={value}" for key, value in data.items())])
    extra = {"event": event, "data": data}
    transaction.on_commit(lambda: logger.info("%s", message, extra=extra))


class RequestIdMiddleware:
    """Gives every request an id, returned as X-Request-ID, and logs one line for it.

    The line has the route, not the path: the AzamPay callback path contains a secret.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        given = request.headers.get("X-Request-ID", "")
        current = given if _VALID_ID.fullmatch(given) else uuid.uuid4().hex
        request.request_id = current
        token = request_id.set(current)
        start = time.perf_counter()
        try:
            response = self.get_response(request)
            response["X-Request-ID"] = current
            match = request.resolver_match
            data = {
                "method": request.method,
                "route": match.route if match else "",
                "status": response.status_code,
                "ms": round((time.perf_counter() - start) * 1000),
            }
            _request_logger.info(
                "%(method)s %(route)s %(status)s %(ms)sms",
                data,
                extra={"event": "request", "data": data},
            )
            return response
        finally:
            request_id.reset(token)


class RequestIdFilter(logging.Filter):
    """Adds `request_id` and the Celery `task_id` to every record."""

    def filter(self, record):
        # Django logs error responses after the middleware has finished.
        request = getattr(record, "request", None)
        record.request_id = request_id.get() or getattr(request, "request_id", "")
        record.task_id = (current_task.request.id if current_task else "") or ""
        return True


def _redact(text: str) -> str:
    secret = settings.AZAMPAY_CALLBACK_TOKEN
    for value in {secret, quote(secret, safe="")} - {""}:
        text = text.replace(value, "[redacted]")
    return text


class TextFormatter(logging.Formatter):
    def __init__(self):
        super().__init__(
            "%(asctime)s %(levelname)s %(name)s [%(request_id)s%(task_id)s] %(message)s"
        )

    def format(self, record):
        return _redact(super().format(record))


class JsonFormatter(logging.Formatter):
    """One JSON object per line."""

    def format(self, record):
        line = {
            **getattr(record, "data", {}),
            "time": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for name in ("request_id", "task_id", "event"):
            if value := getattr(record, name, ""):
                line[name] = value
        if record.exc_info:
            line["exception"] = self.formatException(record.exc_info)
        return _redact(json.dumps(line, default=str, ensure_ascii=False))

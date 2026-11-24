"""Uniform API error shape: `{"detail": str, "code": str, "errors": {field: [msg]}}`."""

from django.core.exceptions import PermissionDenied as DjangoPermissionDenied
from django.http import Http404
from rest_framework import exceptions, status
from rest_framework.response import Response
from rest_framework.settings import api_settings
from rest_framework.views import exception_handler


class Conflict(exceptions.APIException):
    """409 — invalid state transition (used by order/payment services)."""

    status_code = status.HTTP_409_CONFLICT
    default_detail = "This action is not allowed in the current state."
    default_code = "invalid_state"


class GatewayError(exceptions.APIException):
    """502 — upstream payment/messaging provider failure."""

    status_code = status.HTTP_502_BAD_GATEWAY
    default_detail = "Upstream provider error."
    default_code = "gateway_error"


def _as_list(value):
    """Flatten errors to strings; nested (list-of-object) errors become `field: message`."""
    if isinstance(value, list):
        return [message for v in value for message in _as_list(v)]
    if isinstance(value, dict):
        return [f"{key}: {message}" for key, v in value.items() for message in _as_list(v)]
    return [str(value)]


def _first_code(codes):
    if isinstance(codes, dict):
        for value in codes.values():
            return _first_code(value)
    if isinstance(codes, list):
        return _first_code(codes[0]) if codes else "invalid"
    return codes or "invalid"


def api_exception_handler(exc, context):
    if isinstance(exc, Http404):
        exc = exceptions.NotFound()
    elif isinstance(exc, DjangoPermissionDenied):
        exc = exceptions.PermissionDenied()

    response = exception_handler(exc, context)
    if response is None:
        return None

    if isinstance(exc, exceptions.ValidationError):
        detail = exc.detail
        if isinstance(detail, dict):
            errors = {key: _as_list(value) for key, value in detail.items()}
        else:
            errors = {api_settings.NON_FIELD_ERRORS_KEY: _as_list(detail)}
        body = {"detail": "Invalid input.", "code": "invalid", "errors": errors}
    else:
        detail = exc.detail if isinstance(exc, exceptions.APIException) else str(exc)
        if isinstance(detail, dict):
            message = str(detail.get("detail", exc.default_detail))
            code = str(detail.get("code", exc.default_code))
        else:
            message = str(detail)
            code = getattr(detail, "code", None) or _first_code(exc.get_codes())
        body = {"detail": message, "code": code, "errors": {}}

    return Response(body, status=response.status_code, headers=_headers(response))


def _headers(response):
    return {k: v for k, v in response.items() if k in ("WWW-Authenticate", "Retry-After", "Allow")}

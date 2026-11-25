import hashlib
import hmac
import json
import logging

from django.conf import settings
from django.db import transaction
from django.http import HttpResponse
from django.utils.crypto import constant_time_compare
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common.throttling import count_rejected_webhook

from . import services, tasks

logger = logging.getLogger(__name__)


class WhatsAppWebhookView(APIView):
    """Messages from Meta, authenticated by their HMAC signature.

    Anything signed gets 200, even if unusable, so Meta does not keep retrying it.
    """

    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = []  # only rejected requests are limited

    @extend_schema(
        parameters=[
            OpenApiParameter(name, str)
            for name in ("hub.mode", "hub.verify_token", "hub.challenge")
        ],
        responses={200: OpenApiTypes.STR},
        tags=["webhooks"],
    )
    def get(self, request):
        query = request.query_params
        expected = settings.WHATSAPP_VERIFY_TOKEN
        given = query.get("hub.verify_token", "")
        if (
            not expected
            or query.get("hub.mode") != "subscribe"
            or not constant_time_compare(given, expected)
        ):
            count_rejected_webhook(request)
            raise PermissionDenied
        return HttpResponse(query.get("hub.challenge", ""), content_type="text/plain")

    @extend_schema(
        request=OpenApiTypes.OBJECT, responses={200: OpenApiTypes.OBJECT}, tags=["webhooks"]
    )
    def post(self, request):
        body = request.body
        if not _signed(body, request.headers.get("X-Hub-Signature-256", "")):
            count_rejected_webhook(request)
            raise PermissionDenied
        try:
            data = json.loads(body)
        except ValueError:
            logger.warning("WhatsApp webhook ignored: not JSON")
            data = None
        for value in _values(data):
            for message in _dicts(value.get("messages")):
                _receive(message)
            for status in _dicts(value.get("statuses")):
                if isinstance(status.get("id"), str) and isinstance(status.get("status"), str):
                    services.record_delivery(status["id"], status["status"])
                    if status["status"] == "failed":
                        _log_failure(status)
        return Response({"received": True})


def _signed(body: bytes, signature: str) -> bool:
    secret = settings.WHATSAPP_APP_SECRET
    if not secret:
        return False
    digest = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return constant_time_compare(signature, f"sha256={digest}")


def _values(data):
    """The `value` objects about messages addressed to our phone number."""
    for entry in _dicts(data.get("entry") if isinstance(data, dict) else None):
        for change in _dicts(entry.get("changes")):
            if change.get("field") != "messages":
                logger.info("WhatsApp webhook ignored: not about messages")
                continue
            value = change.get("value")
            if not isinstance(value, dict):
                continue
            metadata = value.get("metadata")
            number = metadata.get("phone_number_id") if isinstance(metadata, dict) else None
            expected = settings.WHATSAPP_PHONE_NUMBER_ID
            if expected and number != expected:
                logger.warning("WhatsApp webhook ignored: other phone number")
                continue
            yield value


def _log_failure(status):
    """Meta accepts a message first and reports here why it was not delivered.

    Only numeric codes are logged: the texts may contain private data.
    """
    codes = [e.get("code") for e in _dicts(status.get("errors"))] or [None]
    for code in codes:
        logger.warning(
            "WhatsApp delivery failed (code %s)", code if isinstance(code, int) else None
        )


def _dicts(value):
    return [v for v in value if isinstance(v, dict)] if isinstance(value, list) else []


def _receive(message):
    try:
        stored = services.receive(message)
    except (ValueError, KeyError) as exc:
        logger.warning("WhatsApp message ignored: %s", exc)
        return
    if stored:
        # Robust: without a broker the message still waits for the sweep.
        transaction.on_commit(lambda: tasks.process_message.delay(stored.pk), robust=True)

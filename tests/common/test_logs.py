import json
import logging
import sys
from decimal import Decimal

import pytest

from apps.common.logs import JsonFormatter, RequestIdFilter, TextFormatter, log_event, request_id
from apps.ledger import services as ledger
from apps.payments import services as payments
from tests.factories import AdminFactory, PaymentFactory

VENDORS = "/api/v1/vendors/"
PHONE = "+255712345678"


def record(message="hello", exc_info=None, **extra):
    made = logging.LogRecord("apps.x", logging.INFO, __file__, 1, message, (), exc_info)
    for name, value in extra.items():
        setattr(made, name, value)
    RequestIdFilter().filter(made)
    return made


def events(caplog):
    return [r.event for r in caplog.records if hasattr(r, "event")]


# --- Formatting ------------------------------------------------------------


def test_json_line():
    token = request_id.set("abc")
    try:
        data = json.loads(JsonFormatter().format(record(event="a.b", data={"n": Decimal("1")})))
    finally:
        request_id.reset(token)
    assert data["message"] == "hello"
    assert (data["level"], data["logger"], data["request_id"]) == ("INFO", "apps.x", "abc")
    assert (data["event"], data["n"]) == ("a.b", "1")
    assert data["time"]


def test_json_stays_on_one_line_with_a_traceback():
    try:
        raise ValueError("boom")
    except ValueError:
        line = JsonFormatter().format(record("bad\nnews", sys.exc_info()))
    assert "\n" not in line
    assert "ValueError: boom" in json.loads(line)["exception"]


@pytest.mark.parametrize("formatter", [JsonFormatter(), TextFormatter()])
def test_callback_token_is_redacted_everywhere(settings, formatter):
    settings.AZAMPAY_CALLBACK_TOKEN = "top-secret"
    try:
        raise ValueError("/webhooks/azampay/top-secret/")
    except ValueError:
        line = formatter.format(record("POST /webhooks/azampay/top-secret/", sys.exc_info()))
    assert "top-secret" not in line
    assert "[redacted]" in line


def test_no_token_configured(settings):
    settings.AZAMPAY_CALLBACK_TOKEN = ""
    assert json.loads(JsonFormatter().format(record()))["message"] == "hello"


# --- Requests --------------------------------------------------------------


@pytest.mark.django_db
def test_request_id_is_kept_or_replaced(api_client):
    assert api_client.get(VENDORS, HTTP_X_REQUEST_ID="abc-123")["X-Request-ID"] == "abc-123"
    generated = api_client.get(VENDORS)["X-Request-ID"]
    assert len(generated) == 32
    for bad in ("a b", "x" * 65, "a\tb", '"}'):
        assert api_client.get(VENDORS, HTTP_X_REQUEST_ID=bad)["X-Request-ID"] != bad
    assert request_id.get() == ""


@pytest.mark.django_db
def test_request_line_has_the_route_not_the_path(api_client, caplog, settings):
    token = settings.AZAMPAY_CALLBACK_TOKEN
    with caplog.at_level(logging.INFO):
        api_client.post(f"/api/v1/webhooks/azampay/{token}/?q=private", {}, format="json")
    line = next(r for r in caplog.records if getattr(r, "event", "") == "request")
    assert line.data["method"] == "POST"
    assert line.data["status"] == 200
    assert line.data["route"] == "api/v1/webhooks/azampay/<str:token>/"
    assert line.data["ms"] >= 0
    assert token not in caplog.text
    assert "private" not in caplog.text


def test_unmatched_route(client, caplog):
    with caplog.at_level(logging.INFO, logger="apps"):
        client.get("/nope/")
    line = next(r for r in caplog.records if getattr(r, "event", "") == "request")
    assert (line.data["route"], line.data["status"]) == ("", 404)


# --- Business events -------------------------------------------------------


def test_log_event_waits_for_commit(db, caplog, django_capture_on_commit_callbacks):
    with caplog.at_level(logging.INFO):
        with django_capture_on_commit_callbacks() as callbacks:
            log_event(logging.getLogger("apps.x"), "thing.done", thing="1")
            assert events(caplog) == []
        for callback in callbacks:
            callback()
    assert events(caplog) == ["thing.done"]
    assert "thing=1" in caplog.text


def test_payment_events(db, caplog, django_capture_on_commit_callbacks):
    payment = PaymentFactory(payer_phone=PHONE)
    admin = AdminFactory()
    with caplog.at_level(logging.INFO), django_capture_on_commit_callbacks(execute=True):
        payments.handle_gateway_result(
            payment.pk, success=True, amount=payment.amount, reference="R", raw={}
        )
        ledger.record_payout(
            vendor=payment.order.vendor,
            amount=Decimal("1000"),
            method="bank",
            reference="T",
            actor=admin,
        )
        payment.order.refresh_from_db()
        payments.refund(payment.order, admin, "x")
    found = events(caplog)
    for name in ("payment.succeeded", "payout.recorded", "payment.refunded"):
        assert found.count(name) == 1
    assert PHONE not in caplog.text


def test_started_and_failed_events(db, caplog, django_capture_on_commit_callbacks):
    old = PaymentFactory(status="failed")
    with caplog.at_level(logging.INFO), django_capture_on_commit_callbacks(execute=True):
        payment = payments.start_payment(old.order, method="online", provider="mpesa", phone=PHONE)
        payments.handle_gateway_result(payment.pk, success=False, amount=None, reference="", raw={})
    assert events(caplog).count("payment.started") == 1
    assert events(caplog).count("payment.failed") == 1
    assert PHONE not in caplog.text


def test_django_error_lines_have_the_request_id(client, caplog):
    client.get("/nope/", HTTP_X_REQUEST_ID="abc-123")
    line = next(r for r in caplog.records if r.name == "django.request")
    RequestIdFilter().filter(line)
    assert line.request_id == "abc-123"

import json
import uuid
from datetime import timedelta
from decimal import Decimal

import httpx
import pytest
import respx
from django.core.cache import cache
from django.core.exceptions import ImproperlyConfigured
from django.utils import timezone

from apps.common.exceptions import GatewayError
from apps.payments.gateways import get_gateway
from apps.payments.gateways.azampay import AzamPayGateway
from apps.payments.gateways.mock import MockGateway

AUTH = "https://auth.test/AppRegistration/GenerateToken"
MNO = "https://pay.test/azampay/mno/checkout"
BANK = "https://pay.test/azampay/bank/checkout"
PID = uuid.UUID("11111111-1111-1111-1111-111111111111")


@pytest.fixture(autouse=True)
def azampay(settings):
    cache.clear()
    settings.PAYMENT_GATEWAY = "azampay"
    settings.AZAMPAY_APP_NAME = "app"
    settings.AZAMPAY_CLIENT_ID = "cid"
    settings.AZAMPAY_CLIENT_SECRET = "shh"
    settings.AZAMPAY_API_KEY = "key"
    settings.AZAMPAY_AUTH_BASE_URL = "https://auth.test"
    settings.AZAMPAY_CHECKOUT_BASE_URL = "https://pay.test"
    yield
    cache.clear()


def token(value="tok", expire=None):
    expire = expire or (timezone.now() + timedelta(hours=1)).isoformat()
    return httpx.Response(
        200, json={"data": {"accessToken": value, "expire": expire}, "success": True}
    )


def ok():
    return httpx.Response(200, json={"transactionId": "AZ1", "message": "ok", "success": True})


def pay(**kwargs):
    defaults = {
        "payment_id": PID,
        "amount": Decimal("15000.00"),
        "phone": "+255712345678",
        "provider": "mpesa",
    }
    return get_gateway().checkout_mobile(**defaults | kwargs)


def pay_bank():
    return get_gateway().checkout_bank(
        payment_id=PID,
        amount=Decimal("15000.50"),
        bank_name="CRDB",
        account_number="0150",
        phone="+255712345678",
        otp="987654",
    )


@respx.mock
def test_mno_request_shape_and_token_cache():
    auth = respx.post(AUTH).mock(return_value=token())
    mno = respx.post(MNO).mock(return_value=ok())
    assert pay() == "AZ1"
    pay(provider="halopesa")
    assert auth.call_count == 1
    assert json.loads(auth.calls[0].request.content) == {
        "appName": "app",
        "clientId": "cid",
        "clientSecret": "shh",
    }
    request = mno.calls[0].request
    assert request.headers["Authorization"] == "Bearer tok"
    assert request.headers["X-API-Key"] == "key"
    assert json.loads(request.content) == {
        "accountNumber": "255712345678",
        "amount": "15000",
        "currency": "TZS",
        "externalId": str(PID),
        "provider": "Mpesa",
    }
    assert json.loads(mno.calls[1].request.content)["provider"] == "Halopesa"


@respx.mock
def test_bank_request_shape():
    respx.post(AUTH).mock(return_value=token())
    bank = respx.post(BANK).mock(return_value=ok())
    assert pay_bank() == "AZ1"
    assert json.loads(bank.calls[0].request.content) == {
        "amount": "15000.50",
        "currencyCode": "TZS",
        "merchantAccountNumber": "0150",
        "merchantMobileNumber": "255712345678",
        "otp": "987654",
        "provider": "CRDB",
        "referenceId": str(PID),
    }


@respx.mock
def test_expired_token_response_is_not_cached():
    past = (timezone.now() - timedelta(hours=1)).isoformat()
    auth = respx.post(AUTH).mock(return_value=token(expire=past))
    respx.post(MNO).mock(return_value=ok())
    pay()
    pay()
    assert auth.call_count == 2


@respx.mock
def test_unparseable_expiry_still_works():
    respx.post(AUTH).mock(return_value=token(expire="soon"))
    respx.post(MNO).mock(return_value=ok())
    assert pay() == "AZ1"


@respx.mock
def test_401_refreshes_token_once():
    auth = respx.post(AUTH).mock(side_effect=[token("old"), token("new")])
    mno = respx.post(MNO).mock(side_effect=[httpx.Response(401), ok()])
    assert pay() == "AZ1"
    assert auth.call_count == 2
    assert mno.calls[1].request.headers["Authorization"] == "Bearer new"


@respx.mock
def test_persistent_401():
    respx.post(AUTH).mock(return_value=token())
    mno = respx.post(MNO).mock(return_value=httpx.Response(401))
    with pytest.raises(GatewayError):
        pay()
    assert mno.call_count == 2


@respx.mock
@pytest.mark.parametrize(
    "outcome",
    [
        httpx.ConnectError("down"),
        httpx.ReadTimeout("slow"),
        {"status_code": 500, "text": "boom"},
        {"status_code": 200, "text": "<html>"},
        {"status_code": 200, "json": []},
        {"status_code": 200, "json": {"success": False, "message": "987654 shh"}},
    ],
)
def test_errors_become_gateway_error_without_leaks(outcome, caplog):
    respx.post(AUTH).mock(return_value=token())
    for path in (MNO, BANK):
        if isinstance(outcome, Exception):
            respx.post(path).mock(side_effect=outcome)
        else:
            respx.post(path).mock(return_value=httpx.Response(**outcome))
    for call in (pay, pay_bank):
        with pytest.raises(GatewayError) as exc:
            call()
        for secret in ("987654", "shh"):
            assert secret not in str(exc.value)
            assert secret not in caplog.text


@respx.mock
@pytest.mark.parametrize("body", [{}, {"data": None}, {"data": {}}])
def test_bad_token_response(body):
    respx.post(AUTH).mock(return_value=httpx.Response(200, json=body))
    with pytest.raises(GatewayError):
        pay()


def test_missing_credentials(settings):
    settings.AZAMPAY_API_KEY = ""
    with pytest.raises(ImproperlyConfigured):
        get_gateway()


def test_factory(settings):
    assert isinstance(get_gateway(), AzamPayGateway)
    settings.PAYMENT_GATEWAY = "mock"
    assert isinstance(get_gateway(), MockGateway)
    settings.PAYMENT_GATEWAY = "nope"
    with pytest.raises(ImproperlyConfigured):
        get_gateway()

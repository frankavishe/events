import hashlib
import hmac

import pytest
from django.conf import settings as project_settings
from django.core.cache import cache
from rest_framework.throttling import SimpleRateThrottle

from tests.factories import DEFAULT_PASSWORD, ClientFactory

pytestmark = pytest.mark.django_db

TOKEN = "/api/v1/auth/token/"
REGISTER = "/api/v1/auth/register/"
WHATSAPP = "/api/v1/webhooks/whatsapp/"
VENDORS = "/api/v1/vendors/"


def azampay(token):
    return f"/api/v1/webhooks/azampay/{token}/"


@pytest.fixture
def rates(monkeypatch):
    """Enable the given rates only; the rest stay off, as everywhere in the tests."""
    cache.clear()
    values = dict.fromkeys(project_settings.REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"])
    monkeypatch.setattr(SimpleRateThrottle, "THROTTLE_RATES", values)
    yield values
    cache.clear()


def statuses(call, times):
    return [call().status_code for _ in range(times)]


def test_anonymous_limit_has_the_api_error_shape(api_client, rates):
    rates["anon"] = "2/min"
    assert statuses(lambda: api_client.get(VENDORS), 3) == [200, 200, 429]
    response = api_client.get(VENDORS)
    assert response.json()["code"] == "throttled"
    assert int(response["Retry-After"]) > 0


def test_users_are_limited_separately(auth_client, rates):
    rates["user"] = "1/min"
    first = auth_client(ClientFactory())
    assert statuses(lambda: first.get("/api/v1/me/"), 2) == [200, 429]
    assert auth_client(ClientFactory()).get("/api/v1/me/").status_code == 200


def test_login_limit_follows_the_account_across_formats_and_addresses(api_client, rates):
    rates["login"] = "2/min"
    user = ClientFactory(phone="+255712345678")

    def login(name, ip):
        body = {"login": name, "password": "wrong"}
        return api_client.post(TOKEN, body, REMOTE_ADDR=ip).status_code

    assert login("0712345678", "10.0.0.1") == 401
    assert login("+255 712 345 678", "10.0.0.2") == 401
    assert login("255712345678", "10.0.0.3") == 429
    other = ClientFactory()
    body = {"login": other.phone, "password": DEFAULT_PASSWORD}
    assert api_client.post(TOKEN, body, REMOTE_ADDR="10.0.0.1").status_code == 200
    assert user.phone not in str(list(cache._cache))  # hashed


def test_login_limit_by_email_ignores_case(api_client, rates):
    rates["login"] = "1/min"
    for name, expected in (("a@example.com", 401), (" A@Example.com", 429)):
        body = {"login": name, "password": "x"}
        assert api_client.post(TOKEN, body).status_code == expected


@pytest.mark.parametrize("body", [{}, [], {"login": 5}, {"login": None}])
def test_malformed_login_is_not_an_error(api_client, rates, body):
    rates["login"] = "5/min"
    assert api_client.post(TOKEN, body, format="json").status_code in (400, 401)


def test_login_limit_per_address(api_client, rates):
    rates["login_ip"] = "2/min"
    names = iter(["a@x.com", "b@x.com", "c@x.com"])
    result = statuses(lambda: api_client.post(TOKEN, {"login": next(names), "password": "x"}), 3)
    assert result == [401, 401, 429]


@pytest.mark.parametrize("url", [REGISTER, "/api/v1/auth/register/vendor/"])
def test_registration_limit(api_client, rates, url):
    rates["register"] = "1/hour"
    assert statuses(lambda: api_client.post(url, {}), 2) == [400, 429]


def test_forwarded_header_cannot_be_spoofed(api_client, rates):
    rates["anon"] = "1/min"
    get = lambda n: api_client.get(VENDORS, HTTP_X_FORWARDED_FOR=f"1.1.1.{n}")  # noqa: E731
    assert [get(n).status_code for n in range(2)] == [200, 429]


def test_only_rejected_azampay_callbacks_are_limited(api_client, rates, settings):
    rates.update(anon="1/min", webhook_rejected="2/min")
    bad = statuses(lambda: api_client.post(azampay("wrong"), {}, format="json"), 3)
    assert bad == [404, 404, 429]
    url = azampay(settings.AZAMPAY_CALLBACK_TOKEN)
    good = statuses(lambda: api_client.post(url, {}, format="json"), 5)
    assert good == [200] * 5


def test_only_rejected_whatsapp_messages_are_limited(api_client, rates, settings):
    settings.WHATSAPP_APP_SECRET = "s"
    rates.update(anon="1/min", webhook_rejected="2/min")

    def post(signature):
        return api_client.post(
            WHATSAPP,
            b"{}",
            content_type="application/json",
            HTTP_X_HUB_SIGNATURE_256=signature,
        )

    assert statuses(lambda: post("sha256=bad"), 3) == [403, 403, 429]
    valid = "sha256=" + hmac.new(b"s", b"{}", hashlib.sha256).hexdigest()
    assert statuses(lambda: post(valid), 5) == [200] * 5


def test_rejected_whatsapp_verification_is_limited(api_client, rates):
    rates["webhook_rejected"] = "1/min"
    assert statuses(lambda: api_client.get(WHATSAPP), 2) == [403, 429]


CODE = "/api/v1/auth/password/code/"
PASSWORD = "/api/v1/auth/password/"


@pytest.mark.parametrize("rate", ["password_code", "password_code_day"])
def test_password_code_limit_is_the_same_for_unknown_accounts(api_client, rates, rate):
    rates[rate] = "1/day"
    known = ClientFactory(phone="+255712345678").phone
    for first, second in ((known, "0712345678"), ("0799999999", "+255799999999")):
        result = [api_client.post(CODE, {"login": x}).status_code for x in (first, second)]
        assert result == [202, 429]


def test_password_code_limit_per_address(api_client, rates):
    rates["password_code_ip"] = "2/hour"
    names = iter(["a@x.com", "b@x.com", "c@x.com"])
    assert statuses(lambda: api_client.post(CODE, {"login": next(names)}), 3) == [202, 202, 429]


@pytest.mark.parametrize("rate", ["password_confirm", "password_confirm_ip"])
def test_password_confirm_limits(api_client, rates, rate):
    rates[rate] = "2/min"
    body = {"login": "0712345678", "code": "123456", "password": "Pilau-Tamu-2027"}
    assert statuses(lambda: api_client.post(PASSWORD, body), 3) == [400, 400, 429]
    assert api_client.post(TOKEN, {"login": "0712345678", "password": "x"}).status_code == 401

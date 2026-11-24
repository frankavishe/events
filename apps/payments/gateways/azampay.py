"""AzamPay checkout.

Request shapes follow research.md R3 and a third-party SDK; AzamPay's own documentation could
not be read when this was written. Verify against the sandbox before going live.

Request bodies hold OTPs and account numbers and responses may echo them, so neither is ever
logged or put in an error.
"""

import logging
from datetime import timedelta
from decimal import Decimal

import httpx
from django.conf import settings
from django.core.cache import cache
from django.core.exceptions import ImproperlyConfigured
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from apps.common.exceptions import GatewayError

logger = logging.getLogger(__name__)

TIMEOUT_SECONDS = 20
TOKEN_FALLBACK_SECONDS = 5 * 60  # when the expiry cannot be understood
TOKEN_MAX_SECONDS = 60 * 60
TOKEN_MARGIN = timedelta(seconds=60)
PROVIDERS = {
    "mpesa": "Mpesa",
    "tigo": "Tigo",
    "airtel": "Airtel",
    "halopesa": "Halopesa",
    "azampesa": "Azampesa",
}
REQUIRED_SETTINGS = (
    "AZAMPAY_APP_NAME",
    "AZAMPAY_CLIENT_ID",
    "AZAMPAY_CLIENT_SECRET",
    "AZAMPAY_API_KEY",
    "AZAMPAY_AUTH_BASE_URL",
    "AZAMPAY_CHECKOUT_BASE_URL",
)


class AzamPayGateway:
    def __init__(self):
        missing = [name for name in REQUIRED_SETTINGS if not getattr(settings, name)]
        if missing:
            raise ImproperlyConfigured(f"AzamPay needs: {', '.join(missing)}")
        self.auth_base = settings.AZAMPAY_AUTH_BASE_URL.rstrip("/")
        self.checkout_base = settings.AZAMPAY_CHECKOUT_BASE_URL.rstrip("/")
        self.cache_key = f"azampay-token:{settings.AZAMPAY_CLIENT_ID}"

    def checkout_mobile(self, *, payment_id, amount, phone, provider) -> str | None:
        return self._checkout(
            "/azampay/mno/checkout",
            {
                "accountNumber": _msisdn(phone),
                "amount": _amount(amount),
                "currency": settings.DEFAULT_CURRENCY,
                "externalId": str(payment_id),
                "provider": PROVIDERS[provider],
            },
        )

    def checkout_bank(
        self, *, payment_id, amount, bank_name, account_number, phone, otp
    ) -> str | None:
        return self._checkout(
            "/azampay/bank/checkout",
            {
                "amount": _amount(amount),
                "currencyCode": settings.DEFAULT_CURRENCY,
                "merchantAccountNumber": account_number,
                "merchantMobileNumber": _msisdn(phone),
                "otp": otp,
                "provider": bank_name,
                "referenceId": str(payment_id),
            },
        )

    def _checkout(self, path, body) -> str | None:
        response = self._send_checkout(path, body)
        if response.status_code == httpx.codes.UNAUTHORIZED:
            # Rejected before processing, so repeating it cannot charge twice.
            cache.delete(self.cache_key)
            response = self._send_checkout(path, body)
        data = _json(response, path)
        if data.get("success") is not True:
            logger.warning("AzamPay refused %s", path)
            raise GatewayError
        reference = data.get("transactionId")
        return str(reference) if reference else None

    def _send_checkout(self, path, body):
        headers = {
            "Authorization": f"Bearer {self._token()}",
            "X-API-Key": settings.AZAMPAY_API_KEY,
        }
        return _post(self.checkout_base + path, path, body, headers)

    def _token(self) -> str:
        token = cache.get(self.cache_key)
        if token:
            return token
        path = "/AppRegistration/GenerateToken"
        body = {
            "appName": settings.AZAMPAY_APP_NAME,
            "clientId": settings.AZAMPAY_CLIENT_ID,
            "clientSecret": settings.AZAMPAY_CLIENT_SECRET,
        }
        data = _json(_post(self.auth_base + path, path, body), path).get("data")
        token = data.get("accessToken") if isinstance(data, dict) else None
        if not token or not isinstance(token, str):
            logger.warning("AzamPay returned no access token")
            raise GatewayError
        lifetime = _token_lifetime(data.get("expire"))
        if lifetime > 0:
            cache.set(self.cache_key, token, lifetime)
        return token


def _token_lifetime(expire) -> int:
    try:
        expires_at = parse_datetime(str(expire))
    except ValueError:
        expires_at = None
    if expires_at is None or timezone.is_naive(expires_at):
        return TOKEN_FALLBACK_SECONDS
    remaining = (expires_at - timezone.now() - TOKEN_MARGIN).total_seconds()
    return min(int(remaining), TOKEN_MAX_SECONDS)


def _post(url, path, body, headers=None):
    try:
        return httpx.post(url, json=body, headers=headers, timeout=TIMEOUT_SECONDS)
    except httpx.HTTPError as exc:
        logger.warning("AzamPay %s failed: %s", path, type(exc).__name__)
        raise GatewayError from None


def _json(response, path) -> dict:
    if not response.is_success:
        logger.warning("AzamPay %s returned HTTP %s", path, response.status_code)
        raise GatewayError
    try:
        data = response.json()
    except ValueError:
        data = None
    if not isinstance(data, dict):
        logger.warning("AzamPay %s returned an unexpected body", path)
        raise GatewayError
    return data


def _msisdn(phone: str) -> str:
    return phone.removeprefix("+")


def _amount(amount: Decimal) -> str:
    whole = amount == amount.to_integral_value()
    return f"{amount:.0f}" if whole else f"{amount:.2f}"

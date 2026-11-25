"""Request limits beyond DRF's general anon/user ones. Rates are in settings (None = off)."""

import hashlib

from rest_framework.exceptions import Throttled
from rest_framework.throttling import SimpleRateThrottle

from .phone import InvalidPhoneNumber, normalize_phone


class _AddressThrottle(SimpleRateThrottle):
    def get_cache_key(self, request, view):
        return self.cache_format % {"scope": self.scope, "ident": self.get_ident(request)}


class LoginAddressThrottle(_AddressThrottle):
    """Generous: mobile carriers put many clients behind one address."""

    scope = "login_ip"


class _AccountThrottle(SimpleRateThrottle):
    """Strict limit per account, whatever address the attempts come from."""

    def get_cache_key(self, request, view):
        data = request.data
        login = data.get("login") if hasattr(data, "get") else None
        if not isinstance(login, str) or not login.strip():
            return None  # fails validation anyway
        ident = hashlib.sha256(_canonical(login).encode()).hexdigest()
        return self.cache_format % {"scope": self.scope, "ident": ident}


def _canonical(login: str) -> str:
    """The same for every spelling of one phone number or email."""
    login = login.strip().lower()
    try:
        return login if "@" in login else normalize_phone(login)
    except InvalidPhoneNumber:
        return login


class LoginThrottle(_AccountThrottle):
    scope = "login"


class PasswordCodeThrottle(_AccountThrottle):
    scope = "password_code"


class PasswordCodeDayThrottle(_AccountThrottle):
    scope = "password_code_day"


class PasswordCodeAddressThrottle(_AddressThrottle):
    scope = "password_code_ip"


class PasswordConfirmThrottle(_AccountThrottle):
    scope = "password_confirm"


class PasswordConfirmAddressThrottle(_AddressThrottle):
    scope = "password_confirm_ip"


class RegisterThrottle(_AddressThrottle):
    scope = "register"


class RejectedWebhookThrottle(_AddressThrottle):
    scope = "webhook_rejected"


def count_rejected_webhook(request) -> None:
    """Call before refusing a webhook. Valid ones are never limited: they must not be lost."""
    throttle = RejectedWebhookThrottle()
    if not throttle.allow_request(request, None):
        raise Throttled(throttle.wait())

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

from .azampay import AzamPayGateway
from .base import PaymentGateway
from .mock import MockGateway


def get_gateway() -> PaymentGateway:
    """The gateway selected by `settings.PAYMENT_GATEWAY`."""
    if settings.PAYMENT_GATEWAY == "mock":
        return MockGateway()
    if settings.PAYMENT_GATEWAY == "azampay":
        return AzamPayGateway()
    raise ImproperlyConfigured(f"Unknown PAYMENT_GATEWAY: {settings.PAYMENT_GATEWAY!r}")

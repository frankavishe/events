from django.core.exceptions import ImproperlyConfigured

from . import base
from .base import *  # noqa: F403
from .base import AZAMPAY_CALLBACK_TOKEN, PAYMENT_GATEWAY, env

DEBUG = False
ALLOWED_HOSTS = env.list("DJANGO_ALLOWED_HOSTS")

if PAYMENT_GATEWAY == "mock":
    raise ImproperlyConfigured("PAYMENT_GATEWAY=mock must not be used in production.")
if not AZAMPAY_CALLBACK_TOKEN:
    raise ImproperlyConfigured("AZAMPAY_CALLBACK_TOKEN is required in production.")
for _name in ("MESSAGING_PROVIDER", "LLM_PROVIDER"):
    if getattr(base, _name) == "fake":
        raise ImproperlyConfigured(f"{_name}=fake must not be used in production.")
for _name in (
    "WHATSAPP_ACCESS_TOKEN",
    "WHATSAPP_PHONE_NUMBER_ID",
    "WHATSAPP_VERIFY_TOKEN",
    "WHATSAPP_APP_SECRET",
    "GEMINI_API_KEY",
):
    if not getattr(base, _name):
        raise ImproperlyConfigured(f"{_name} is required in production.")

SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_SSL_REDIRECT = env.bool("DJANGO_SECURE_SSL_REDIRECT", default=True)
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_HSTS_SECONDS = env.int("DJANGO_SECURE_HSTS_SECONDS", default=60 * 60 * 24 * 30)
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_CONTENT_TYPE_NOSNIFF = True

REST_FRAMEWORK = {
    **REST_FRAMEWORK,  # noqa: F405
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
}

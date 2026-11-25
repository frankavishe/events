"""Test settings: no network, no real credentials, Celery runs inline."""

import os

os.environ.setdefault("DJANGO_SECRET_KEY", "test-secret-key-not-for-production")
os.environ.setdefault("DATABASE_URL", "postgres://events:events@localhost:5435/events")

from .base import *  # noqa: F403
from .base import MIDDLEWARE, REST_FRAMEWORK

# Nothing is collected in tests.
MIDDLEWARE = [m for m in MIDDLEWARE if not m.startswith("whitenoise.")]

DEBUG = False
ALLOWED_HOSTS = ["testserver", "localhost"]

PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]

CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}

CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = True
CELERY_BROKER_URL = "memory://"
CELERY_RESULT_BACKEND = "cache+memory://"

# Off, except in the throttling tests.
REST_FRAMEWORK = {
    **REST_FRAMEWORK,
    "DEFAULT_THROTTLE_RATES": dict.fromkeys(REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"]),
    "NUM_PROXIES": 0,
}

PAYMENT_GATEWAY = "mock"
AZAMPAY_CALLBACK_TOKEN = "test-callback-token"  # noqa: S105
LLM_PROVIDER = "fake"
MESSAGING_PROVIDER = "fake"
WHATSAPP_PHONE_NUMBER_ID = ""
WHATSAPP_GRAPH_VERSION = "v26.0"
WHATSAPP_TEMPLATE_NEW_ORDER = "new_order"
WHATSAPP_TEMPLATE_ORDER_STATUS = "order_status"
WHATSAPP_TEMPLATE_PAYMENT_FAILED = "payment_failed"
WHATSAPP_TEMPLATE_AUTH_CODE = "auth_code"

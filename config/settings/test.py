"""Test settings: no network, no real credentials, Celery runs inline."""

import os

os.environ.setdefault("DJANGO_SECRET_KEY", "test-secret-key-not-for-production")
os.environ.setdefault("DATABASE_URL", "postgres://events:events@localhost:5435/events")

from .base import *  # noqa: F403

DEBUG = False
ALLOWED_HOSTS = ["testserver", "localhost"]

PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]

CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}

CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = True
CELERY_BROKER_URL = "memory://"
CELERY_RESULT_BACKEND = "cache+memory://"

PAYMENT_GATEWAY = "mock"
AZAMPAY_CALLBACK_TOKEN = "test-callback-token"  # noqa: S105
LLM_PROVIDER = "fake"
MESSAGING_PROVIDER = "fake"
WHATSAPP_PHONE_NUMBER_ID = ""
WHATSAPP_GRAPH_VERSION = "v26.0"
WHATSAPP_TEMPLATE_NEW_ORDER = "new_order"
WHATSAPP_TEMPLATE_ORDER_STATUS = "order_status"
WHATSAPP_TEMPLATE_PAYMENT_FAILED = "payment_failed"

"""Base settings shared by every environment. Secrets come from the environment (.env)."""

from datetime import timedelta
from pathlib import Path

import environ

BASE_DIR = Path(__file__).resolve().parent.parent.parent

env = environ.Env()
environ.Env.read_env(BASE_DIR / ".env")

SECRET_KEY = env("DJANGO_SECRET_KEY")
DEBUG = env.bool("DJANGO_DEBUG", default=False)
ALLOWED_HOSTS = env.list("DJANGO_ALLOWED_HOSTS", default=[])

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # third party
    "rest_framework",
    "rest_framework_simplejwt",
    "django_filters",
    "drf_spectacular",
    "django_celery_beat",
    # local
    "apps.common",
    "apps.accounts",
    "apps.vendors",
    "apps.catalog",
    "apps.events",
    "apps.orders",
    "apps.payments",
    "apps.ledger",
    "apps.notifications",
    "apps.chatbot",
]

MIDDLEWARE = [
    "apps.common.logs.RequestIdMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.locale.LocaleMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

DATABASES = {"default": env.db("DATABASE_URL")}
DATABASES["default"]["ATOMIC_REQUESTS"] = False

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
AUTH_USER_MODEL = "accounts.User"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# Locale (constitution: Africa/Dar_es_Salaam, TZS, en + sw)
LANGUAGE_CODE = "en"
LANGUAGES = [("en", "English"), ("sw", "Kiswahili")]
TIME_ZONE = "Africa/Dar_es_Salaam"
USE_I18N = True
USE_TZ = True
DEFAULT_CURRENCY = "TZS"
DEFAULT_PHONE_REGION_CODE = "255"

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"

# Cache / Redis
REDIS_URL = env("REDIS_URL", default="redis://localhost:6379/0")
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.redis.RedisCache",
        "LOCATION": REDIS_URL,
    }
}

# Celery
CELERY_BROKER_URL = env("CELERY_BROKER_URL", default=REDIS_URL)
CELERY_RESULT_BACKEND = env("CELERY_RESULT_BACKEND", default=REDIS_URL)
CELERY_TIMEZONE = TIME_ZONE
CELERY_TASK_ALWAYS_EAGER = False
CELERY_BEAT_SCHEDULER = "django_celery_beat.schedulers:DatabaseScheduler"
CELERY_BEAT_SCHEDULE = {
    "expire-pending-orders": {
        "task": "apps.orders.tasks.expire_pending_orders",
        "schedule": timedelta(minutes=15),
    },
    "reconcile-pending-payments": {
        "task": "apps.payments.tasks.reconcile_pending_payments",
        "schedule": timedelta(minutes=15),
    },
    "resume-stuck-messages": {
        "task": "apps.chatbot.tasks.resume_stuck_messages",
        "schedule": timedelta(minutes=1),
    },
}

# DRF
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework_simplejwt.authentication.JWTAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    "DEFAULT_FILTER_BACKENDS": [
        "django_filters.rest_framework.DjangoFilterBackend",
        "rest_framework.filters.SearchFilter",
        "rest_framework.filters.OrderingFilter",
    ],
    "DEFAULT_PAGINATION_CLASS": "apps.common.pagination.StandardPagination",
    "PAGE_SIZE": 20,
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "EXCEPTION_HANDLER": "apps.common.exceptions.api_exception_handler",
    "COERCE_DECIMAL_TO_STRING": True,
    "DEFAULT_THROTTLE_CLASSES": [
        "rest_framework.throttling.AnonRateThrottle",
        "rest_framework.throttling.UserRateThrottle",
    ],
    # See apps/common/throttling.py.
    "DEFAULT_THROTTLE_RATES": {
        "anon": env("THROTTLE_ANON", default="300/min"),
        "user": env("THROTTLE_USER", default="300/min"),
        "login": env("THROTTLE_LOGIN", default="10/min"),
        "login_ip": env("THROTTLE_LOGIN_IP", default="60/min"),
        "register": env("THROTTLE_REGISTER", default="60/hour"),
        "webhook_rejected": env("THROTTLE_WEBHOOK_REJECTED", default="30/min"),
    },
    # Proxies in front of the app; 0 ignores X-Forwarded-For, which clients can forge.
    "NUM_PROXIES": env.int("DJANGO_NUM_PROXIES", default=0),
}

# Logging
CELERY_WORKER_HIJACK_ROOT_LOGGER = False
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "filters": {"request_id": {"()": "apps.common.logs.RequestIdFilter"}},
    "formatters": {
        "text": {"()": "apps.common.logs.TextFormatter"},
        "json": {"()": "apps.common.logs.JsonFormatter"},
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "filters": ["request_id"],
            "formatter": "text",
        }
    },
    "root": {"handlers": ["console"], "level": env("LOG_LEVEL", default="INFO")},
    "loggers": {
        # Without their own handlers, so that everything is redacted by our formatters.
        "django": {"handlers": [], "level": "INFO", "propagate": True},
        "django.server": {"handlers": [], "level": "WARNING", "propagate": True},
        # These log full URLs of outgoing requests.
        "httpx": {"level": "WARNING"},
        "httpcore": {"level": "WARNING"},
    },
}

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=env.int("JWT_ACCESS_MINUTES", default=30)),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=env.int("JWT_REFRESH_DAYS", default=7)),
    "ROTATE_REFRESH_TOKENS": True,
    "UPDATE_LAST_LOGIN": True,
    "AUTH_HEADER_TYPES": ("Bearer",),
    "SIGNING_KEY": env("JWT_SIGNING_KEY", default="") or SECRET_KEY,
}

SPECTACULAR_SETTINGS = {
    "TITLE": "Event Catering & Drinks Marketplace API",
    "DESCRIPTION": "Backend API for booking food and drinks for events (Tanzania).",
    "VERSION": "1.0.0",
    "SERVE_INCLUDE_SCHEMA": False,
    "COMPONENT_SPLIT_REQUEST": True,
    "ENUM_NAME_OVERRIDES": {
        "OrderStatusEnum": "apps.orders.models.Order.Status",
        "PaymentStatusEnum": "apps.payments.models.Payment.Status",
        "VendorStatusEnum": "apps.vendors.models.VendorProfile.Status",
        "ChannelEnum": "apps.orders.models.Order.Channel",
        "PaymentMethodEnum": "apps.payments.models.Payment.Method",
        "PayoutMethodEnum": "apps.vendors.models.VendorProfile.PayoutMethod",
    },
}

# Integrations (documented in .env.example)
PAYMENT_GATEWAY = env("PAYMENT_GATEWAY", default="mock")
# How long an online payment blocks a new attempt, and when it is flagged for review.
PAYMENT_PENDING_MINUTES = 30
AZAMPAY_APP_NAME = env("AZAMPAY_APP_NAME", default="")
AZAMPAY_CLIENT_ID = env("AZAMPAY_CLIENT_ID", default="")
AZAMPAY_CLIENT_SECRET = env("AZAMPAY_CLIENT_SECRET", default="")
AZAMPAY_API_KEY = env("AZAMPAY_API_KEY", default="")
AZAMPAY_AUTH_BASE_URL = env(
    "AZAMPAY_AUTH_BASE_URL", default="https://authenticator-sandbox.azampay.co.tz"
)
AZAMPAY_CHECKOUT_BASE_URL = env(
    "AZAMPAY_CHECKOUT_BASE_URL", default="https://sandbox.azampay.co.tz"
)
AZAMPAY_CALLBACK_TOKEN = env("AZAMPAY_CALLBACK_TOKEN", default="")
MESSAGING_PROVIDER = env("MESSAGING_PROVIDER", default="fake")
WHATSAPP_ACCESS_TOKEN = env("WHATSAPP_ACCESS_TOKEN", default="")
WHATSAPP_PHONE_NUMBER_ID = env("WHATSAPP_PHONE_NUMBER_ID", default="")
WHATSAPP_VERIFY_TOKEN = env("WHATSAPP_VERIFY_TOKEN", default="")
WHATSAPP_APP_SECRET = env("WHATSAPP_APP_SECRET", default="")
WHATSAPP_GRAPH_VERSION = env("WHATSAPP_GRAPH_VERSION", default="v26.0")
# Approved templates (en and sw) for messages outside the 24 h window; empty = not sent.
WHATSAPP_TEMPLATE_NEW_ORDER = env("WHATSAPP_TEMPLATE_NEW_ORDER", default="")
WHATSAPP_TEMPLATE_ORDER_STATUS = env("WHATSAPP_TEMPLATE_ORDER_STATUS", default="")
WHATSAPP_TEMPLATE_PAYMENT_FAILED = env("WHATSAPP_TEMPLATE_PAYMENT_FAILED", default="")
LLM_PROVIDER = env("LLM_PROVIDER", default="fake")
GEMINI_API_KEY = env("GEMINI_API_KEY", default="")
GEMINI_MODEL = env("GEMINI_MODEL", default="gemini-3.8-flash")

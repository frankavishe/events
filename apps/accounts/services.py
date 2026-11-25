"""Account business logic shared by REST views and the WhatsApp assistant."""

import logging
import secrets
from datetime import timedelta

from django.contrib.auth import password_validation
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.utils import timezone
from django.utils.crypto import constant_time_compare, salted_hmac
from django.utils.translation import gettext_lazy as _
from rest_framework import status
from rest_framework.exceptions import APIException, ValidationError
from rest_framework_simplejwt.tokens import RefreshToken

from apps.common.logs import log_event
from apps.common.phone import InvalidPhoneNumber
from apps.notifications import enqueue

from .models import PasswordCode, User

logger = logging.getLogger(__name__)

CODE_LIFETIME = timedelta(minutes=10)
MAX_CODE_ATTEMPTS = 5


class InvalidCode(APIException):
    """Deliberately the same for every reason, including an unknown account."""

    status_code = status.HTTP_400_BAD_REQUEST
    default_detail = _("The code is wrong or has expired.")
    default_code = "invalid_code"


@transaction.atomic
def register_client(
    *,
    phone: str,
    full_name: str,
    password: str | None,
    email: str | None = None,
    preferred_language: str = User.Language.EN,
    created_via: str = User.CreatedVia.API,
) -> User:
    """`password=None` creates a user who must set one by code to use the API (WhatsApp)."""
    return User.objects.create_user(
        phone=phone,
        full_name=full_name,
        password=password,
        email=email,
        preferred_language=preferred_language,
        role=User.Role.CLIENT,
        created_via=created_via,
    )


def tokens_for(user: User) -> dict[str, str]:
    refresh = RefreshToken.for_user(user)
    return {"refresh": str(refresh), "access": str(refresh.access_token)}


def check_password_strength(password: str, user: User) -> None:
    try:
        password_validation.validate_password(password, user=user)
    except DjangoValidationError as exc:
        raise ValidationError({"password": list(exc.messages)}) from exc


# --- Setting a password with a one-time code ---------------------------------


def may_use_codes(user: User) -> bool:
    """Operators cannot: a code is weaker protection than their access deserves."""
    return (
        user.is_active
        and user.role in (User.Role.CLIENT, User.Role.VENDOR)
        and not (user.is_staff or user.is_superuser)
    )


def _eligible_user(login: str) -> User | None:
    try:
        user = User.objects.get_by_login(login)
    except (User.DoesNotExist, InvalidPhoneNumber):
        return None
    return user if may_use_codes(user) else None


def request_password_code(login: str) -> None:
    """Send a code to the account's phone. Says nothing about whether the account exists."""
    if user := _eligible_user(login):
        enqueue.password_code(user)
        log_event(logger, "password.code_requested", user=user.pk)


def issue_code(user: User) -> str:
    """Replace any earlier code of the user. Called only where the code is sent."""
    code = f"{secrets.randbelow(1_000_000):06d}"
    PasswordCode.objects.update_or_create(
        user=user,
        defaults={
            "code_hash": _hash(user, code),
            "expires_at": timezone.now() + CODE_LIFETIME,
            "attempts": 0,
            "used_at": None,
        },
    )
    return code


def set_password_with_code(login: str, code: str, password: str) -> User:
    """Raises InvalidCode, or ValidationError for a weak password (the code stays usable)."""
    user = _eligible_user(login)
    if user is None or not _try_code(user, code, password):
        raise InvalidCode
    return user


@transaction.atomic
def _try_code(user, code, password) -> bool:
    """Returns instead of raising on a wrong code, so that the attempt is committed."""
    row = PasswordCode.objects.select_for_update().filter(user=user).first()
    if (
        row is None
        or row.used_at
        or row.expires_at <= timezone.now()
        or row.attempts >= MAX_CODE_ATTEMPTS
    ):
        return False
    if not constant_time_compare(row.code_hash, _hash(user, code)):
        row.attempts += 1
        row.save(update_fields=["attempts", "updated_at"])
        return False
    check_password_strength(password, user)
    user.set_password(password)
    user.save(update_fields=["password", "updated_at"])
    row.used_at = timezone.now()
    row.save(update_fields=["used_at", "updated_at"])
    log_event(logger, "password.changed", user=user.pk)
    return True


def _hash(user, code) -> str:
    # The phone is included so that a code dies with the number it was sent to.
    value = f"{user.pk}:{user.phone}:{code}"
    return salted_hmac("accounts.password_code", value, algorithm="sha256").hexdigest()

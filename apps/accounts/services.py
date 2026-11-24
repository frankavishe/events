"""Account business logic shared by REST views (and later the WhatsApp assistant)."""

from django.db import transaction
from rest_framework_simplejwt.tokens import RefreshToken

from .models import User


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
    """`password=None` creates a user who cannot sign in to the API (WhatsApp)."""
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

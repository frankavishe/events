from django.contrib.auth.base_user import AbstractBaseUser, BaseUserManager
from django.contrib.auth.models import PermissionsMixin
from django.db import models
from django.db.models.functions import Lower
from django.utils.translation import gettext_lazy as _

from apps.common.models import BaseModel
from apps.common.phone import normalize_phone


class UserManager(BaseUserManager):
    use_in_migrations = True

    def _create_user(self, phone, full_name, password, **extra):
        if not phone:
            raise ValueError("Users must have a phone number.")
        email = extra.pop("email", None)
        user = self.model(
            phone=normalize_phone(phone),
            full_name=full_name,
            email=self.normalize_email(email).lower() if email else None,
            **extra,
        )
        if password:
            user.set_password(password)
        else:
            user.set_unusable_password()  # e.g. WhatsApp-created users
        user.save(using=self._db)
        return user

    def create_user(self, phone, full_name="", password=None, **extra):
        extra.setdefault("is_staff", False)
        extra.setdefault("is_superuser", False)
        return self._create_user(phone, full_name, password, **extra)

    def create_superuser(self, phone, full_name="", password=None, **extra):
        extra.setdefault("is_staff", True)
        extra.setdefault("is_superuser", True)
        extra.setdefault("role", User.Role.ADMIN)
        if not extra["is_staff"] or not extra["is_superuser"]:
            raise ValueError("Superuser must have is_staff=True and is_superuser=True.")
        return self._create_user(phone, full_name, password, **extra)

    def get_by_login(self, login: str):
        """Find a user by email (case-insensitive) or by phone in any accepted format."""
        login = (login or "").strip()
        if "@" in login:
            return self.get(email__iexact=login)
        return self.get(phone=normalize_phone(login))


class User(BaseModel, AbstractBaseUser, PermissionsMixin):
    class Role(models.TextChoices):
        CLIENT = "client", _("Client")
        VENDOR = "vendor", _("Vendor")
        ADMIN = "admin", _("Admin")

    class Language(models.TextChoices):
        EN = "en", _("English")
        SW = "sw", _("Kiswahili")

    class CreatedVia(models.TextChoices):
        API = "api", _("API")
        WHATSAPP = "whatsapp", _("WhatsApp")

    phone = models.CharField(_("phone"), max_length=16, unique=True, help_text="E.164")
    # NULL (not "") for "no email", so the unique constraint allows many users without one.
    email = models.EmailField(_("email"), blank=True, null=True)  # noqa: DJ001
    full_name = models.CharField(_("full name"), max_length=150)
    role = models.CharField(max_length=10, choices=Role.choices, default=Role.CLIENT)
    preferred_language = models.CharField(
        max_length=2, choices=Language.choices, default=Language.EN
    )
    created_via = models.CharField(
        max_length=10, choices=CreatedVia.choices, default=CreatedVia.API
    )
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)

    objects = UserManager()

    USERNAME_FIELD = "phone"
    REQUIRED_FIELDS = ["full_name"]

    class Meta:
        ordering = ("-created_at",)
        constraints = [
            models.UniqueConstraint(
                Lower("email"),
                name="accounts_user_email_ci_unique",
                condition=models.Q(email__isnull=False),
            )
        ]

    def __str__(self):
        return f"{self.full_name} ({self.phone})"

    def clean(self):
        super().clean()
        if self.email:
            self.email = self.__class__.objects.normalize_email(self.email).lower()

    def save(self, *args, **kwargs):
        if not self.email:
            self.email = None
        else:
            self.email = self.email.strip().lower()
        super().save(*args, **kwargs)

    @property
    def is_client(self) -> bool:
        return self.role == self.Role.CLIENT

    @property
    def is_vendor(self) -> bool:
        return self.role == self.Role.VENDOR

    @property
    def is_platform_admin(self) -> bool:
        return self.role == self.Role.ADMIN or self.is_superuser

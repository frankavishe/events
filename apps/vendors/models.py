from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.common.models import BaseModel


class ServiceArea(BaseModel):
    name = models.CharField(max_length=100, unique=True)

    class Meta:
        ordering = ("name",)

    def __str__(self):
        return self.name


class VendorProfile(BaseModel):
    class Status(models.TextChoices):
        PENDING = "pending", _("Pending")
        APPROVED = "approved", _("Approved")
        SUSPENDED = "suspended", _("Suspended")
        REJECTED = "rejected", _("Rejected")

    class PayoutMethod(models.TextChoices):
        MOBILE_MONEY = "mobile_money", _("Mobile money")
        BANK = "bank", _("Bank")

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="vendor_profile"
    )
    business_name = models.CharField(max_length=150)
    description = models.TextField(blank=True)
    contact_phone = models.CharField(max_length=16, help_text="E.164")
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    min_notice_days = models.PositiveSmallIntegerField(default=2)
    offers_food = models.BooleanField(default=False)
    offers_drinks = models.BooleanField(default=False)
    service_areas = models.ManyToManyField(ServiceArea, related_name="vendors", blank=True)
    payout_method = models.CharField(max_length=12, choices=PayoutMethod.choices, blank=True)
    payout_account_name = models.CharField(max_length=150, blank=True)
    payout_account_number = models.CharField(max_length=50, blank=True)
    payout_provider = models.CharField(max_length=50, blank=True)

    class Meta:
        ordering = ("-created_at",)
        constraints = [
            models.CheckConstraint(
                name="vendors_offers_something",
                condition=models.Q(offers_food=True) | models.Q(offers_drinks=True),
                violation_error_message=_("A vendor must offer food or drinks."),
            )
        ]

    def __str__(self):
        return self.business_name

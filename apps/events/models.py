from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.common.models import BaseModel


class Event(BaseModel):
    class Type(models.TextChoices):
        WEDDING = "wedding", _("Wedding")
        BIRTHDAY = "birthday", _("Birthday")
        CORPORATE = "corporate", _("Corporate")
        FUNERAL = "funeral", _("Funeral")
        GRADUATION = "graduation", _("Graduation")
        RELIGIOUS = "religious", _("Religious")
        OTHER = "other", _("Other")

    client = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="events"
    )
    event_type = models.CharField(max_length=12, choices=Type.choices)
    title = models.CharField(max_length=150)
    starts_at = models.DateTimeField()
    venue = models.CharField(max_length=255)
    service_area = models.ForeignKey(
        "vendors.ServiceArea",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="events",
    )
    guest_count = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ("starts_at", "id")
        constraints = [
            models.CheckConstraint(
                name="events_guest_count_positive", condition=models.Q(guest_count__gte=1)
            )
        ]

    def __str__(self):
        return self.title

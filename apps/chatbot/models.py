from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.accounts.models import User
from apps.common.models import BaseModel
from apps.common.phone import InvalidPhoneNumber, normalize_phone


class Conversation(BaseModel):
    """One WhatsApp user. Meta may hide the phone and send only a business-scoped id."""

    # NULL (not "") for unknown, so the unique constraints allow many.
    wa_id = models.CharField(max_length=32, unique=True, null=True, blank=True)
    bsuid = models.CharField(max_length=160, unique=True, null=True, blank=True)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="conversations",
    )
    language = models.CharField(
        max_length=2, choices=User.Language.choices, default=User.Language.EN
    )
    last_inbound_at = models.DateTimeField(null=True, blank=True)
    state = models.JSONField(default=dict, blank=True)
    # Held by the worker answering this conversation; expires if that worker dies.
    processing_until = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("-created_at",)
        constraints = [
            models.CheckConstraint(
                name="chatbot_conversation_has_an_id",
                condition=models.Q(wa_id__isnull=False) | models.Q(bsuid__isnull=False),
            )
        ]

    def __str__(self):
        return self.wa_id or self.bsuid

    @property
    def phone(self) -> str | None:
        """E.164 phone vouched for by Meta, if visible."""
        if not self.wa_id:
            return None
        try:
            return normalize_phone(f"+{self.wa_id}")
        except InvalidPhoneNumber:
            return None


class ChatMessage(BaseModel):
    class Direction(models.TextChoices):
        IN = "in", _("In")
        OUT = "out", _("Out")

    class Role(models.TextChoices):
        USER = "user", _("User")
        MODEL = "model", _("Model")
        TOOL = "tool", _("Tool")

    class Status(models.TextChoices):
        RECEIVED = "received", _("Received")
        PROCESSED = "processed", _("Processed")
        FAILED = "failed", _("Failed")
        QUEUED = "queued", _("Queued")
        SENT = "sent", _("Sent")

    # Sequential, not a UUID: order matters and clocks can give two rows the same time.
    id = models.BigAutoField(primary_key=True)
    conversation = models.ForeignKey(
        Conversation, on_delete=models.CASCADE, related_name="messages"
    )
    # The inbound message that everything produced while answering it belongs to.
    reply_to = models.ForeignKey(
        "self", on_delete=models.CASCADE, null=True, blank=True, related_name="replies"
    )
    direction = models.CharField(max_length=3, choices=Direction.choices)
    role = models.CharField(max_length=5, choices=Role.choices)
    wa_message_id = models.CharField(max_length=255, unique=True, null=True, blank=True)
    message_type = models.CharField(max_length=30, default="text")
    text = models.TextField(blank=True)
    tool_name = models.CharField(max_length=200, blank=True)
    # Model rows: {"raw": provider content}. Tool rows: {"results": [...]}. NULL: plain text.
    payload = models.JSONField(null=True, blank=True)
    status = models.CharField(
        max_length=10, choices=Status.choices, default=Status.RECEIVED, db_index=True
    )
    delivery_status = models.CharField(max_length=20, blank=True)
    attempts = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ("id",)
        indexes = [models.Index(fields=["conversation", "id"])]

    def __str__(self):
        return f"{self.role}: {self.text[:40]}"

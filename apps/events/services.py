"""Event business logic shared by REST views (and later the WhatsApp assistant)."""

from django.utils import timezone
from django.utils.translation import gettext as _
from rest_framework.exceptions import ValidationError

from .models import Event


def events_for(client):
    return Event.objects.filter(client=client)


def save_event(event: Event, **changes) -> Event:
    """Create or update `event`. A new or changed date must be in the future."""
    starts_at = changes.get("starts_at", event.starts_at)
    if starts_at != event.starts_at and starts_at <= timezone.now():
        raise ValidationError({"starts_at": _("The event date must be in the future.")})
    for field, value in changes.items():
        setattr(event, field, value)
    event.save()
    return event


def delete_event(event: Event) -> None:
    # Delivery Phase 3 (orders): block when the event has non-cancelled orders.
    event.delete()

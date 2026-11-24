"""Event business logic shared by REST views (and later the WhatsApp assistant)."""

from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext as _
from rest_framework.exceptions import ValidationError

from apps.common.exceptions import Conflict

from .models import Event


def events_for(client):
    return Event.objects.filter(client=client)


@transaction.atomic
def save_event(event: Event, **changes) -> Event:
    """Create or update `event`. A new or changed date must be in the future."""
    starts_at = changes.get("starts_at", event.starts_at)
    if starts_at != event.starts_at:
        if starts_at <= timezone.now():
            raise ValidationError({"starts_at": _("The event date must be in the future.")})
        # Vendors accepted orders for the old date, with their minimum notice.
        if not event._state.adding and _has_live_orders(event):
            raise Conflict(
                _("The date cannot change while the event has active orders."),
                code="event_has_orders",
            )
    for field, value in changes.items():
        setattr(event, field, value)
    event.save()
    return event


@transaction.atomic
def delete_event(event: Event) -> None:
    if _has_live_orders(event):
        raise Conflict(
            _("This event has orders. Cancel them before deleting it."), code="event_has_orders"
        )
    event.delete()


def _has_live_orders(event) -> bool:
    # Local import: orders depends on events, not the other way round.
    from apps.orders.services import has_live_orders

    # Order creation locks the event too, so none can appear after this check.
    Event.objects.select_for_update().filter(pk=event.pk).first()
    return has_live_orders(event)

import django_filters as filters

from .models import Order


class OrderFilter(filters.FilterSet):
    # A plain UUID, so the filter cannot be used to probe for other clients' events.
    event = filters.UUIDFilter(field_name="event_id")

    class Meta:
        model = Order
        fields = ("status",)

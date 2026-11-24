from drf_spectacular.utils import extend_schema
from rest_framework import viewsets
from rest_framework.filters import OrderingFilter

from apps.common.permissions import IsClient

from . import services
from .models import Event
from .serializers import EventSerializer


@extend_schema(tags=["events"])
class EventViewSet(viewsets.ModelViewSet):
    """The authenticated client's own events."""

    queryset = Event.objects.none()  # for schema generation
    serializer_class = EventSerializer
    permission_classes = [IsClient]
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]
    filter_backends = [OrderingFilter]
    ordering_fields = ("starts_at", "created_at")

    def get_queryset(self):
        return services.events_for(self.request.user)

    def perform_create(self, serializer):
        serializer.save(client=self.request.user)

    def perform_destroy(self, instance):
        services.delete_event(instance)

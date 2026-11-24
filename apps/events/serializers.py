from rest_framework import serializers

from . import services
from .models import Event


class EventSerializer(serializers.ModelSerializer):
    class Meta:
        model = Event
        fields = (
            "id",
            "event_type",
            "title",
            "starts_at",
            "venue",
            "service_area",
            "guest_count",
            "notes",
            "created_at",
        )
        read_only_fields = ("id", "created_at")

    def create(self, validated_data):
        return services.save_event(Event(), **validated_data)

    def update(self, instance, validated_data):
        return services.save_event(instance, **validated_data)

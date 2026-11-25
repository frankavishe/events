import uuid

from django.db import models


class BaseModel(models.Model):
    """Abstract base for every domain model: UUID primary key plus timestamps."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True
        ordering = ("-created_at",)


def ascending_ids(count: int) -> list[uuid.UUID]:
    """Ids for rows saved in sequence whose order matters.

    Such rows sort by (created_at, id), and the clock may not advance between two saves.
    """
    return sorted(uuid.uuid4() for _ in range(count))

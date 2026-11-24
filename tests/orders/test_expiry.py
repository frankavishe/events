from datetime import timedelta

import pytest
from django.conf import settings
from django.utils import timezone
from freezegun import freeze_time

from apps.orders.tasks import expire_pending_orders
from tests.factories import OrderFactory

pytestmark = pytest.mark.django_db


def test_expires_only_overdue_pending_orders():
    overdue, confirmed = OrderFactory(), OrderFactory(status="confirmed")
    now = timezone.now()
    with freeze_time(now + timedelta(hours=23, minutes=59)):
        assert expire_pending_orders() == 0
    fresh = OrderFactory(expires_at=now + timedelta(hours=30))
    with freeze_time(now + timedelta(hours=24, minutes=1)):
        assert expire_pending_orders() == 1
        assert expire_pending_orders() == 0
    for order, status in ((overdue, "expired"), (confirmed, "confirmed"), (fresh, "pending")):
        order.refresh_from_db()
        assert order.status == status
    change = overdue.status_changes.get()
    assert (change.to_status, change.actor) == ("expired", None)


def test_schedule_points_at_real_tasks():
    from config.celery import app

    app.loader.import_default_modules()
    assert len(settings.CELERY_BEAT_SCHEDULE) == 2
    for entry in settings.CELERY_BEAT_SCHEDULE.values():
        assert entry["task"] in app.tasks

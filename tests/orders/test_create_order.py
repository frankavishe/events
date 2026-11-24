import re
import uuid
from datetime import datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest
from django.utils import timezone
from freezegun import freeze_time
from rest_framework.exceptions import ValidationError

from apps.orders import services
from apps.orders.models import Order
from tests.factories import (
    ClientFactory,
    EventFactory,
    ItemFactory,
    PackageFactory,
    VendorProfileFactory,
)

pytestmark = pytest.mark.django_db


@pytest.fixture
def vendor():
    return VendorProfileFactory()


@pytest.fixture
def event():
    return EventFactory()


@pytest.fixture
def place(event, vendor):
    def _place(*lines, **overrides):
        kwargs = {
            "client": event.client,
            "event_id": event.pk,
            "vendor_id": vendor.pk,
            "lines": list(lines),
        } | overrides
        return services.create_order(**kwargs)

    return _place


def line(obj, quantity=10):
    key = "package_id" if obj._meta.model_name == "package" else "item_id"
    return {key: obj.pk, "quantity": quantity}


def assert_rejected(place, field, *lines, **overrides):
    with pytest.raises(ValidationError) as exc:
        place(*lines, **overrides)
    assert field in exc.value.detail
    assert not Order.objects.exists()


def test_totals_snapshots_and_audit(place, vendor, event):
    item = ItemFactory(vendor=vendor, unit_price=Decimal("1500.50"))
    package = PackageFactory(vendor=vendor, price=Decimal("25000"))
    before = timezone.now()
    order = place(line(item, 3), line(package, 100), notes="Asante")

    assert order.total == order.subtotal == Decimal("2504501.50")
    assert (order.status, order.channel, order.client) == ("pending", "api", event.client)
    assert re.fullmatch(r"EVT-\d{6}-[A-Z0-9]{4}", order.reference)
    assert before + timedelta(hours=24) <= order.expires_at <= timezone.now() + timedelta(hours=24)
    first, second = order.lines.all()
    assert (first.name_snapshot, first.unit_snapshot) == (item.name, "plate")
    assert (first.unit_price_snapshot, first.line_total) == (
        Decimal("1500.50"),
        Decimal("4501.50"),
    )
    assert (second.unit_snapshot, second.line_total) == ("per_guest", Decimal("2500000"))
    change = order.status_changes.get()
    assert (change.from_status, change.to_status) == ("", "pending")
    assert change.actor == event.client


def test_later_price_change_and_deletion_do_not_alter_order(place, vendor):
    item = ItemFactory(vendor=vendor)
    order = place(line(item))
    name = item.name
    item.unit_price, item.name = Decimal("99999"), "New"
    item.save()
    item.delete()
    order.refresh_from_db()
    kept = order.lines.get()
    assert order.total == Decimal("150000.00")
    assert (kept.item, kept.name_snapshot, kept.unit_price_snapshot) == (
        None,
        name,
        Decimal("15000.00"),
    )


def test_flat_package(place, vendor):
    package = PackageFactory(vendor=vendor, pricing="flat", price=Decimal("500000"), min_guests=50)
    assert place(line(package, 2)).total == Decimal("1000000")


def test_minimum_quantities(place, vendor):
    item = ItemFactory(vendor=vendor, min_quantity=20)
    package = PackageFactory(vendor=vendor, min_guests=50)
    assert_rejected(place, "lines", line(item, 19))
    assert_rejected(place, "lines", line(package, 49))
    with pytest.raises(ValidationError, match="20"):
        place(line(item, 19))
    assert place(line(item, 20), line(package, 50))


@pytest.mark.parametrize("quantity", [0, -1])
def test_non_positive_quantity(place, vendor, quantity):
    assert_rejected(place, "lines", line(ItemFactory(vendor=vendor), quantity))


def test_unavailable_item_and_package(place, vendor):
    assert_rejected(place, "lines", line(ItemFactory(vendor=vendor, is_available=False)))
    assert_rejected(place, "lines", line(PackageFactory(vendor=vendor, is_available=False)))


def test_mixed_vendors(place, vendor):
    assert_rejected(place, "lines", line(ItemFactory(vendor=vendor)), line(ItemFactory()))


def test_malformed_lines(place, vendor):
    item, package = ItemFactory(vendor=vendor), PackageFactory(vendor=vendor)
    assert_rejected(place, "lines")
    assert_rejected(place, "lines", line(item), line(item))
    assert_rejected(place, "lines", {"quantity": 1})
    assert_rejected(place, "lines", line(item) | line(package))
    assert_rejected(place, "lines", {"item_id": uuid.uuid4(), "quantity": 1})


@pytest.mark.parametrize("status", ["pending", "suspended", "rejected"])
def test_unapproved_vendor(place, vendor, status):
    item = ItemFactory(vendor=vendor)
    vendor.status = status
    vendor.save()
    assert_rejected(place, "vendor_id", line(item))


def test_inactive_vendor_user(place, vendor):
    item = ItemFactory(vendor=vendor)
    vendor.user.is_active = False
    vendor.user.save()
    assert_rejected(place, "vendor_id", line(item))


def test_someone_elses_event(place, vendor):
    assert_rejected(place, "event_id", line(ItemFactory(vendor=vendor)), client=ClientFactory())


def test_past_event(place, vendor, event):
    vendor.min_notice_days = 0
    vendor.save()
    event.starts_at = timezone.now() - timedelta(minutes=1)
    event.save()
    assert_rejected(place, "event_id", line(ItemFactory(vendor=vendor)))


def test_min_notice_counts_local_calendar_days(place, vendor, event):
    vendor.min_notice_days = 2
    vendor.save()
    eat = ZoneInfo("Africa/Dar_es_Salaam")
    event.starts_at = datetime(2027, 3, 3, 0, 30, tzinfo=eat)  # still 2 March in UTC
    event.save()
    item = ItemFactory(vendor=vendor)
    with freeze_time(datetime(2027, 3, 2, 0, 10, tzinfo=eat)):
        assert_rejected(place, "event_id", line(item))
    with freeze_time(datetime(2027, 3, 1, 23, 0, tzinfo=eat)):
        assert place(line(item))


@pytest.mark.parametrize("as_package", [False, True])
def test_alcohol_needs_age_confirmation(place, vendor, as_package):
    product = ItemFactory(vendor=vendor, kind="drink", is_alcoholic=True)
    if as_package:
        product = PackageFactory(vendor=vendor, items=[product])
    assert_rejected(place, "age_confirmed", line(product))
    order = place(line(product), age_confirmed=True)
    assert order.contains_alcohol
    assert order.age_confirmed


def test_total_overflow(place, vendor):
    item = ItemFactory(vendor=vendor, unit_price=Decimal("9999999999.99"))
    assert_rejected(place, "lines", line(item, 2))
    assert_rejected(place, "lines", line(item, 10**12))


def test_reference_collision_is_retried(place, vendor, monkeypatch):
    item = ItemFactory(vendor=vendor)
    taken = place(line(item)).reference
    values = iter([taken, "EVT-260101-FREE"])
    monkeypatch.setattr(services, "generate_reference", lambda: next(values))
    assert place(line(item)).reference == "EVT-260101-FREE"

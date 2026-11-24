"""Real threads on committed rows. Rows are removed by hand instead of with a transactional
test, because a table flush would also wipe migration-seeded data from the reused database."""

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from decimal import Decimal
from threading import Barrier

import pytest
from django.db import connection
from django.utils import timezone

from apps.accounts.models import User
from apps.common.exceptions import Conflict
from apps.ledger.models import VendorEarning
from apps.orders import services as orders
from apps.orders.models import Order
from apps.payments import services
from apps.payments.models import Payment
from tests.factories import PaymentFactory


@pytest.fixture
def payment(django_db_setup, django_db_blocker):
    with django_db_blocker.unblock():
        payment = PaymentFactory()
        order = payment.order
        users = [order.client_id, order.vendor.user_id]
        yield payment
        VendorEarning.objects.filter(order=order).delete()
        Payment.objects.filter(order=order).delete()
        Order.objects.filter(pk=order.pk).delete()
        User.objects.filter(pk__in=users).delete()
        connection.close()


def race(*functions):
    barrier = Barrier(len(functions))

    def run(function):
        try:
            barrier.wait(timeout=10)
            return function()
        except Conflict as exc:
            return exc
        finally:
            connection.close()

    with ThreadPoolExecutor(len(functions)) as pool:
        return list(pool.map(run, functions))


def success(payment):
    return services.handle_gateway_result(
        payment.pk, success=True, amount=Decimal("150000"), reference=str(payment.pk), raw={}
    )


def test_duplicate_callbacks_create_one_earning(payment):
    race(*[lambda: success(payment)] * 6)
    assert VendorEarning.objects.filter(order=payment.order).count() == 1
    assert payment.order.status_changes.filter(to_status="paid").count() == 1


def test_cancel_versus_success(payment):
    Payment.objects.filter(pk=payment.pk).update(created_at=timezone.now() - timedelta(minutes=31))
    race(
        lambda: success(payment),
        lambda: orders.transition(payment.order, "cancelled", payment.order.client),
    )
    payment.refresh_from_db()
    payment.order.refresh_from_db()
    earnings = VendorEarning.objects.filter(order=payment.order).count()
    outcome = (payment.order.status, payment.status, earnings)
    assert outcome in {("paid", "success", 1), ("cancelled", "failed", 0)}


def test_concurrent_pay_starts_one_payment(payment):
    Payment.objects.filter(pk=payment.pk).update(status="failed")
    results = race(
        *[
            lambda: services.start_payment(
                payment.order, method="online", provider="mpesa", phone="+255712345678"
            )
        ]
        * 4
    )
    assert sum(isinstance(r, Conflict) for r in results) == 3
    assert Payment.objects.filter(order=payment.order, status="pending").count() == 1

"""Called by business services. Nothing is sent on rollback, and a broker fault cannot break
the order or payment, because the callbacks run after commit and are robust."""

from django.db import transaction

from . import tasks


def new_order(order) -> None:
    _after_commit(tasks.notify_new_order, order)


def status_changed(change) -> None:
    _after_commit(tasks.notify_status, change)


def payment_failed(payment) -> None:
    _after_commit(tasks.notify_payment_failed, payment)


def _after_commit(task, instance):
    transaction.on_commit(lambda: task.delay(str(instance.pk)), robust=True)

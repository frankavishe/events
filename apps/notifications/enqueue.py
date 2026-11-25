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


def password_code(user) -> None:
    # Dropped if the workers are behind: an unexpected late code would only confuse.
    _after_commit(tasks.send_password_code, user, expires=600)


def _after_commit(task, instance, **options):
    transaction.on_commit(lambda: task.apply_async((str(instance.pk),), **options), robust=True)

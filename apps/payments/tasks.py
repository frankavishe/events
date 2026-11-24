from celery import shared_task

from . import services


@shared_task
def reconcile_pending_payments() -> int:
    """Flag online payments that never received a result, for an operator to check."""
    return services.flag_stale_payments()

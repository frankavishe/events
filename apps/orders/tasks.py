from celery import shared_task

from . import services


@shared_task
def expire_pending_orders() -> int:
    """Expire orders the vendor did not answer within 24 hours."""
    return services.expire_overdue()

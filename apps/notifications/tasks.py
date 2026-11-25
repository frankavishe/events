import logging

from celery import shared_task
from django.apps import apps
from django.conf import settings
from django.utils import timezone

from apps.common.money import format_tzs

from . import services
from .clients import MessagingError

logger = logging.getLogger(__name__)

RETRY_SECONDS = 30


def _send(task, function=services.send, **kwargs):
    try:
        function(**kwargs)
    except MessagingError as exc:
        if exc.transient:
            raise task.retry(exc=exc, countdown=RETRY_SECONDS * 2**task.request.retries) from None
        logger.error("Notification %s was refused by the provider", task.name)


# Models are looked up at run time: orders and payments import this module.


@shared_task(bind=True, max_retries=3)
def notify_new_order(self, order_id):
    orders = apps.get_model("orders", "Order").objects.select_related("vendor__user", "event")
    order = orders.filter(pk=order_id).first()
    if order is None:
        return
    date = f"{timezone.localtime(order.event.starts_at):%d/%m/%Y}" if order.event else "-"
    _send(
        self,
        phone=order.vendor.contact_phone,
        language=order.vendor.user.preferred_language,
        texts=services.NEW_ORDER,
        params=[order.reference, date, format_tzs(order.total)],
        template=settings.WHATSAPP_TEMPLATE_NEW_ORDER,
    )


@shared_task(bind=True, max_retries=3)
def notify_status(self, change_id):
    changes = apps.get_model("orders", "OrderStatusChange").objects
    change = changes.select_related("order__client").filter(pk=change_id).first()
    if change is None:
        return
    order, language = change.order, change.order.client.preferred_language
    _send(
        self,
        phone=order.client.phone,
        language=language,
        texts=services.ORDER_STATUS,
        params=[
            order.reference,
            services.STATUS_NAMES[language][change.to_status],
            format_tzs(order.total),
        ],
        template=settings.WHATSAPP_TEMPLATE_ORDER_STATUS,
        extra=change.note if change.to_status == "declined" else "",
    )


@shared_task(bind=True, max_retries=3)
def notify_payment_failed(self, payment_id):
    payments = apps.get_model("payments", "Payment").objects
    payment = payments.select_related("order__client").filter(pk=payment_id).first()
    if payment is None:
        return
    _send(
        self,
        phone=payment.order.client.phone,
        language=payment.order.client.preferred_language,
        texts=services.PAYMENT_FAILED,
        params=[payment.order.reference, format_tzs(payment.amount)],
        template=settings.WHATSAPP_TEMPLATE_PAYMENT_FAILED,
    )


@shared_task(bind=True, max_retries=3)
def send_password_code(self, user_id):
    """The code is made here, so that it never reaches the broker. A retry makes a new one."""
    from apps.accounts import services as accounts  # it imports this module

    user = apps.get_model("accounts", "User").objects.filter(pk=user_id).first()
    if user is None or not accounts.may_use_codes(user):
        return
    if not settings.WHATSAPP_TEMPLATE_AUTH_CODE:
        logger.error("Password code not sent: WHATSAPP_TEMPLATE_AUTH_CODE is not set")
        return
    code = accounts.issue_code(user)
    _send(
        self,
        services.send_auth_code,
        phone=user.phone,
        language=user.preferred_language,
        code=code,
    )

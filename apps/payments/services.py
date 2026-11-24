"""Payment business logic shared by REST views (and later the WhatsApp assistant).

Lock order is always order row first, then payment row.
"""

import logging
from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.common.exceptions import Conflict
from apps.ledger import services as ledger
from apps.notifications import enqueue as notify
from apps.orders import services as orders
from apps.orders.models import Order

from .gateways import get_gateway
from .models import Payment

logger = logging.getLogger(__name__)

Method, Provider, Status = Payment.Method, Payment.Provider, Payment.Status
ReviewReason = Payment.ReviewReason


def payments_for(user):
    return Payment.objects.select_related("order").filter(order__in=orders.orders_for(user))


# --- Starting a payment ----------------------------------------------------


def start_payment(
    order: Order,
    *,
    method: str,
    provider: str = "",
    phone: str = "",
    bank_name: str = "",
    account_number: str = "",
    otp: str = "",
) -> Payment:
    """Start paying `order`. `account_number` and `otp` go to the gateway and are not stored."""
    if method == Method.CASH:
        return _start_cash(order)

    payment = _open_online(order, provider=provider, phone=phone, bank_name=bank_name)
    # Outside any transaction: no row stays locked during the network call.
    try:
        gateway = get_gateway()
        common = {"payment_id": payment.pk, "amount": payment.amount, "phone": phone}
        if provider == Provider.BANK:
            reference = gateway.checkout_bank(
                **common, bank_name=bank_name, account_number=account_number, otp=otp
            )
        else:
            reference = gateway.checkout_mobile(**common, provider=provider)
    except Exception:
        # If the request did reach the gateway, a later success callback still applies.
        _update_if_pending(payment, status=Status.FAILED)
        raise
    if reference:
        _store_reference(payment, reference)
    payment.refresh_from_db()
    return payment


@transaction.atomic
def _start_cash(order) -> Payment:
    order = orders.lock_order(order.pk)
    _block_if_paying_online(order)
    order = orders.transition(order, Order.Status.AWAITING_CASH, order.client)
    return Payment.objects.create(
        order=order, method=Method.CASH, provider=Provider.CASH, amount=order.total
    )


@transaction.atomic
def _open_online(order, **fields) -> Payment:
    order = orders.lock_order(order.pk)
    if order.status not in orders.PAYABLE:
        raise Conflict(_("An order that is %(status)s cannot be paid.") % {"status": order.status})
    _block_if_paying_online(order)
    # Whatever is left is stale. Its late success, if any, is still handled.
    _pending(order, Method.ONLINE).update(status=Status.FAILED, updated_at=timezone.now())
    return Payment.objects.create(
        order=order,
        method=Method.ONLINE,
        provider=fields["provider"],
        payer_phone=fields["phone"],
        bank_name=fields["bank_name"],
        amount=order.total,
    )


def _store_reference(payment, reference):
    reference = reference[:128]
    if Payment.objects.filter(gateway_reference=reference).exclude(pk=payment.pk).exists():
        logger.warning("Gateway reference reused; not stored for payment %s", payment.pk)
        return
    # The callback may have arrived first; its reference wins.
    Payment.objects.filter(pk=payment.pk, gateway_reference=None).update(
        gateway_reference=reference, updated_at=timezone.now()
    )


def _update_if_pending(payment, **changes):
    Payment.objects.filter(pk=payment.pk, status=Status.PENDING).update(
        **changes, updated_at=timezone.now()
    )


def _pending(order, method):
    return Payment.objects.filter(order=order, method=method, status=Status.PENDING)


def _stale_before():
    return timezone.now() - timedelta(minutes=settings.PAYMENT_PENDING_MINUTES)


def _block_if_paying_online(order):
    if _pending(order, Method.ONLINE).filter(created_at__gt=_stale_before()).exists():
        raise Conflict(
            _("An online payment for this order is in progress."), code="payment_in_progress"
        )


def release_for_cancellation(order) -> None:
    """Called by orders, with the order locked, before it is cancelled."""
    _block_if_paying_online(order)
    _cancel_pending_cash(order)


def _cancel_pending_cash(order):
    _pending(order, Method.CASH).update(status=Status.CANCELLED, updated_at=timezone.now())


# --- Results ---------------------------------------------------------------


@transaction.atomic
def handle_gateway_result(
    payment_id, *, success: bool, amount: Decimal | None, reference: str, raw: dict
) -> Payment | None:
    """Apply a gateway result. Safe to repeat and to receive out of order.

    Returns None for an unknown payment. A success never regresses.
    """
    found = Payment.objects.filter(pk=payment_id, method=Method.ONLINE).first()
    if found is None:
        return None
    order = orders.lock_order(found.order_id)
    payment = Payment.objects.select_for_update().get(pk=found.pk)
    if payment.status == Status.SUCCESS:
        return payment

    payment.raw_callback = raw
    reference = reference[:128]
    if not success:
        first_report = payment.status == Status.PENDING
        payment.status = Status.FAILED
        payment.save()
        # Not for repeats, or for a stale attempt after the order was paid or cancelled.
        if first_report and order.status in orders.PAYABLE:
            notify.payment_failed(payment)
        return payment

    problem = _problem(order, payment, amount, reference)
    if problem:
        payment.status = Status.FAILED
        payment.needs_review, payment.review_reason = True, problem
        payment.save()
        logger.error("Payment %s needs review: %s", payment.pk, problem.value)
        return payment

    payment.gateway_reference = reference or payment.gateway_reference
    payment.needs_review, payment.review_reason = False, ""
    _cancel_pending_cash(order)
    _settle(order, payment, actor=None)
    return payment


def _problem(order, payment, amount, reference):
    if amount is None or amount != payment.amount:
        return ReviewReason.AMOUNT_MISMATCH
    if order.status not in orders.PAYABLE:
        return ReviewReason.NOT_PAYABLE
    used = Payment.objects.filter(gateway_reference=reference).exclude(pk=payment.pk)
    if reference and used.exists():
        return ReviewReason.DUPLICATE_REFERENCE
    return None


def _settle(order, payment, *, actor):
    """Mark paid and record the earning, in the caller's transaction."""
    payment.status = Status.SUCCESS
    payment.completed_at = timezone.now()
    payment.save()
    payment.order = orders.transition(order, Order.Status.PAID, actor)
    ledger.record_earning(payment)


@transaction.atomic
def confirm_cash(order_id, actor) -> Order:
    """The order's vendor or an admin confirms that cash was received."""
    order = orders.lock_order(order_id)
    payment = _pending(order, Method.CASH).select_for_update().first()
    if payment is None:
        # Reports the right error: forbidden for strangers, otherwise a conflict.
        orders.check_vendor_or_admin(order, actor)
        raise Conflict(_("This order is not awaiting a cash payment."))
    payment.confirmed_by = actor
    _settle(order, payment, actor=actor)
    return payment.order


@transaction.atomic
def refund(order: Order, actor, note: str) -> Order:
    """Record a refund made outside the system and reverse the vendor's earning."""
    order = orders.transition(order, Order.Status.REFUNDED, actor, note)
    ledger.reverse_earning(order)
    return order


def flag_stale_payments() -> int:
    """Flag online payments still pending after the allowed time. Returns how many."""
    return Payment.objects.filter(
        method=Method.ONLINE,
        status=Status.PENDING,
        needs_review=False,
        created_at__lte=_stale_before(),
    ).update(needs_review=True, review_reason=ReviewReason.NO_CALLBACK, updated_at=timezone.now())

"""Order business logic shared by REST views (and later the WhatsApp assistant)."""

import secrets
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal

from django.db import IntegrityError, transaction
from django.utils import timezone
from django.utils.translation import gettext as _
from rest_framework.exceptions import PermissionDenied, ValidationError

from apps.catalog.models import Package
from apps.catalog.services import public_items, public_packages
from apps.common.exceptions import Conflict
from apps.common.money import MONEY_DECIMAL_PLACES, MONEY_MAX_DIGITS, to_money
from apps.common.permissions import is_admin
from apps.events.models import Event
from apps.events.services import events_for
from apps.notifications import enqueue as notify
from apps.vendors.models import VendorProfile
from apps.vendors.services import public_vendors

from .models import Order, OrderLine, OrderStatusChange

Status = Order.Status

EXPIRY = timedelta(hours=24)
MAX_TOTAL_EXCLUSIVE = 10 ** (MONEY_MAX_DIGITS - MONEY_DECIMAL_PLACES)

# No 0/O/1/I/L, so references can be read out over the phone.
REFERENCE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
REFERENCE_ATTEMPTS = 5

CLIENT, VENDOR, ADMIN, SYSTEM = "client", "vendor", "admin", "system"

# {from: {to: who}}
ALLOWED = {
    Status.PENDING: {
        Status.CONFIRMED: {VENDOR, ADMIN},
        Status.DECLINED: {VENDOR, ADMIN},
        Status.EXPIRED: {SYSTEM},
        Status.CANCELLED: {CLIENT, ADMIN},
    },
    Status.CONFIRMED: {
        Status.AWAITING_CASH: {CLIENT},
        Status.PAID: {SYSTEM},
        Status.CANCELLED: {CLIENT, ADMIN},
    },
    Status.AWAITING_CASH: {
        Status.PAID: {SYSTEM, VENDOR, ADMIN},
        Status.CANCELLED: {CLIENT, ADMIN},
    },
    Status.PAID: {
        Status.FULFILLED: {VENDOR, ADMIN},
        Status.REFUNDED: {ADMIN},
    },
    Status.FULFILLED: {
        Status.COMPLETED: {VENDOR, ADMIN, SYSTEM},
        Status.REFUNDED: {ADMIN},
    },
    Status.COMPLETED: {Status.REFUNDED: {ADMIN}},
}

# Orders that no longer commit anyone to anything.
DEAD = (Status.CANCELLED, Status.DECLINED, Status.EXPIRED)
PAYABLE = (Status.CONFIRMED, Status.AWAITING_CASH)

# --- Queries ---------------------------------------------------------------


def orders_for(user):
    """Orders `user` may see: admins all, vendors theirs, clients their own."""
    orders = Order.objects.select_related("event", "client", "vendor")
    if is_admin(user):
        return orders
    if user.is_vendor:
        return orders.filter(vendor__user=user)
    return orders.filter(client=user)


def with_details(orders):
    return orders.prefetch_related("lines", "payments", "status_changes__actor")


def lock_order(pk) -> Order:
    """Row lock. Always taken before any payment lock, so the two cannot deadlock."""
    return (
        Order.objects.select_for_update(of=("self",))
        .select_related("event", "client", "vendor__user")
        .get(pk=pk)
    )


def has_live_orders(event) -> bool:
    return event.orders.exclude(status__in=DEAD).exists()


# --- State machine ---------------------------------------------------------


def _roles(order, actor) -> set[str]:
    if actor is None:
        return {SYSTEM}
    roles = set()
    if is_admin(actor):
        roles.add(ADMIN)
    if order.client_id == actor.pk:
        roles.add(CLIENT)
    if order.vendor.user_id == actor.pk:
        roles.add(VENDOR)
    return roles


def check_vendor_or_admin(order, actor) -> None:
    if not _roles(order, actor) & {VENDOR, ADMIN}:
        raise PermissionDenied


@transaction.atomic
def transition(order: Order, to: str, actor, note: str = "") -> Order:
    """Move `order` to status `to`. `actor=None` is the system. Returns the updated order."""
    order = lock_order(order.pk)
    source = order.status
    roles = _roles(order, actor)
    if not roles:
        raise PermissionDenied
    allowed = ALLOWED.get(source, {}).get(to)
    if allowed is None:
        raise Conflict(
            _("An order that is %(source)s cannot become %(target)s.")
            % {"source": source, "target": str(to)}
        )
    if not roles & allowed:
        raise PermissionDenied
    _check_guards(order, to)

    order.status = to
    order.save(update_fields=["status", "updated_at"])
    change = _log(order, source, actor, note)
    if actor is None or actor.pk != order.client_id:  # clients know what they did themselves
        notify.status_changed(change)
    return order


def _check_guards(order, to):
    now = timezone.now()
    if to == Status.CONFIRMED:
        if order.expires_at <= now:
            raise Conflict(_("The time to respond to this order has passed."))
        if order.vendor.status != VendorProfile.Status.APPROVED:
            raise Conflict(_("The vendor is not approved."))
    elif to == Status.COMPLETED:
        if order.event is None or order.event.starts_at > now:
            raise Conflict(_("The event has not taken place yet."))
    elif to == Status.CANCELLED:
        # Local import: payments depends on orders, not the other way round.
        from apps.payments.services import release_for_cancellation

        release_for_cancellation(order)


def _log(order, source, actor, note="") -> OrderStatusChange:
    return OrderStatusChange.objects.create(
        order=order, from_status=source, to_status=order.status, actor=actor, note=note
    )


def expire_overdue() -> int:
    """Expire pending orders past their deadline. Returns how many were expired."""
    overdue = Order.objects.filter(status=Status.PENDING, expires_at__lte=timezone.now())
    expired = 0
    for order in overdue:
        try:
            transition(order, Status.EXPIRED, None)
        except Conflict:  # the vendor or client acted first
            continue
        expired += 1
    return expired


# --- Creation --------------------------------------------------------------


def generate_reference() -> str:
    suffix = "".join(secrets.choice(REFERENCE_ALPHABET) for _i in range(4))
    return f"EVT-{timezone.localdate():%y%m%d}-{suffix}"


@dataclass(frozen=True)
class Quote:
    event: Event
    vendor: VendorProfile
    lines: list[OrderLine]  # unsaved
    total: Decimal
    contains_alcohol: bool


def quote_order(*, client, event_id, vendor_id, lines: list[dict]) -> Quote:
    """Validate and price an order without placing it. Age is checked when it is placed."""
    return _quote(events_for(client), event_id, vendor_id, lines)


def _quote(events, event_id, vendor_id, lines) -> Quote:
    event = events.filter(pk=event_id).first()
    if event is None:
        raise ValidationError({"event_id": _("Event not found.")})
    vendor = public_vendors().filter(pk=vendor_id).first()
    if vendor is None:
        raise ValidationError({"vendor_id": _("This vendor is not available.")})
    _check_notice(event, vendor)
    built, contains_alcohol = _build_lines(vendor, lines)
    total = sum(line.line_total for line in built)
    if total >= MAX_TOTAL_EXCLUSIVE:
        raise ValidationError({"lines": _("The order total is too large.")})
    return Quote(event, vendor, built, total, contains_alcohol)


@transaction.atomic
def create_order(
    *,
    client,
    event_id,
    vendor_id,
    lines: list[dict],
    age_confirmed: bool = False,
    notes: str = "",
    channel: str = Order.Channel.API,
) -> Order:
    """Place an order. Each line is `{"item_id" or "package_id": UUID, "quantity": int}`."""
    # Locked, so the event cannot be moved or deleted while the order is being placed.
    quote = _quote(events_for(client).select_for_update(), event_id, vendor_id, lines)
    if quote.contains_alcohol and not age_confirmed:
        raise ValidationError(
            {"age_confirmed": _("Confirm that you are 18 or older to order alcohol.")}
        )

    order = _insert_order(
        Order(
            client=client,
            event=quote.event,
            vendor=quote.vendor,
            subtotal=quote.total,
            total=quote.total,
            contains_alcohol=quote.contains_alcohol,
            age_confirmed=age_confirmed,
            channel=channel,
            notes=notes,
            expires_at=timezone.now() + EXPIRY,
        )
    )
    for line in quote.lines:  # one by one, so created_at keeps the given order
        line.order = order
        line.save()
    _log(order, "", client)
    notify.new_order(order)
    return order


def _check_notice(event, vendor):
    if event.starts_at <= timezone.now():
        raise ValidationError({"event_id": _("The event date has passed.")})
    notice = (timezone.localdate(event.starts_at) - timezone.localdate()).days
    if notice < vendor.min_notice_days:
        raise ValidationError(
            {
                "event_id": _("This vendor needs at least %(days)d days' notice.")
                % {"days": vendor.min_notice_days}
            }
        )


def _build_lines(vendor, lines) -> tuple[list[OrderLine], bool]:
    """Validate lines against the vendor's public catalog and snapshot their prices."""
    if not lines:
        raise ValidationError({"lines": _("An order needs at least one line.")})
    if any(bool(line.get("item_id")) == bool(line.get("package_id")) for line in lines):
        raise ValidationError({"lines": _("Each line needs either an item or a package.")})
    keys = [line.get("item_id") or line.get("package_id") for line in lines]
    if len(set(keys)) != len(keys):
        raise ValidationError({"lines": _("Each item or package can appear only once.")})

    items = public_items().filter(vendor=vendor).in_bulk(_ids(lines, "item_id"))
    packages = public_packages().filter(vendor=vendor).in_bulk(_ids(lines, "package_id"))
    built, contains_alcohol = [], False
    for line, key in zip(lines, keys, strict=True):
        product = items.get(key) if line.get("item_id") else packages.get(key)
        if product is None:
            raise ValidationError(
                {"lines": _("%(id)s is not available from this vendor.") % {"id": key}}
            )
        built.append(_build_line(product, line["quantity"]))
        contains_alcohol |= (
            product.contains_alcohol if isinstance(product, Package) else product.is_alcoholic
        )
    return built, contains_alcohol


def _ids(lines, key):
    return [line[key] for line in lines if line.get(key)]


def _build_line(product, quantity) -> OrderLine:
    if isinstance(product, Package):
        per_guest = product.pricing == Package.Pricing.PER_GUEST
        minimum = product.min_guests if per_guest else 1
        unit, price, target = product.pricing, product.price, {"package": product}
    else:
        minimum = product.min_quantity
        unit, price, target = product.unit, product.unit_price, {"item": product}
    if quantity < minimum:
        raise ValidationError(
            {
                "lines": _("The minimum quantity for %(name)s is %(minimum)d.")
                % {"name": product.name, "minimum": minimum}
            }
        )
    return OrderLine(
        name_snapshot=product.name,
        unit_snapshot=unit,
        unit_price_snapshot=price,
        quantity=quantity,
        line_total=to_money(price * quantity),
        **target,
    )


def _insert_order(order) -> Order:
    for attempt in range(REFERENCE_ATTEMPTS):
        order.reference = generate_reference()
        try:
            with transaction.atomic():
                order.save(force_insert=True)
        except IntegrityError:
            taken = Order.objects.filter(reference=order.reference).exists()
            if not taken or attempt == REFERENCE_ATTEMPTS - 1:
                raise
        else:
            return order
    raise AssertionError("unreachable")

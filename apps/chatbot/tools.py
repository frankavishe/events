"""What the assistant can do. Every tool calls the same services and validation as the API.

The sender comes from the conversation, never from the model. Order tools see only the sender's
own orders as a client. No transaction is opened around a tool, so `start_payment` holds no locks
during its network call.
"""

import hashlib
import json
import logging
import re
from dataclasses import dataclass
from uuid import UUID

from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone
from rest_framework.exceptions import APIException, ValidationError

from apps.accounts.models import User
from apps.accounts.services import register_client as create_client
from apps.catalog import services as catalog
from apps.catalog.filters import ItemFilter, PackageFilter
from apps.catalog.models import Package
from apps.common.exceptions import error_messages
from apps.common.money import format_tzs
from apps.events.models import Event
from apps.events.serializers import EventSerializer
from apps.events.services import events_for
from apps.orders import services as orders
from apps.orders.models import Order
from apps.orders.serializers import OrderCreateSerializer
from apps.payments import services as payments
from apps.payments.models import Payment
from apps.payments.serializers import PaySerializer
from apps.vendors.filters import VendorFilter
from apps.vendors.models import ServiceArea
from apps.vendors.services import public_vendors

from .models import ChatMessage, Conversation

logger = logging.getLogger(__name__)

GENERIC_ERROR = "Something went wrong. Apologise and ask the user to try again later."
MAX_RESULTS = 10
MOBILE_PROVIDERS = ["mpesa", "tigo", "airtel", "halopesa", "azampesa"]


class ToolError(Exception):
    """A problem to explain to the user."""


@dataclass
class Context:
    conversation: Conversation
    inbound: ChatMessage

    @property
    def client(self) -> User:
        user = self.conversation.user
        if user is None:
            raise ToolError("The user is not registered. Ask their name and call register_client.")
        if not user.is_active or user.role != User.Role.CLIENT:
            raise ToolError("Only active client accounts can book or see orders here.")
        return user

    def order(self, reference) -> Order:
        order = _own_orders(self.client).filter(reference=str(reference).strip().upper()).first()
        if order is None:
            raise ToolError("The user has no order with this reference.")
        return order


def run(name: str, args: dict, conversation, inbound) -> dict:
    """Run a tool. Never raises: problems come back as `{"error": ...}`."""
    function = TOOLS.get(name)
    if function is None:
        return {"error": "There is no such tool."}
    try:
        return function(Context(conversation, inbound), **args)
    except ToolError as exc:
        return {"error": str(exc)}
    except APIException as exc:
        return {"error": "; ".join(error_messages(exc.detail))}
    except Exception:
        logger.exception("Tool %s failed", name)
        return {"error": GENERIC_ERROR}


# --- Catalog ---------------------------------------------------------------


def search_catalog(
    ctx,
    query="",
    kind=None,
    alcoholic=None,
    service_area=None,
    max_price=None,
    limit=MAX_RESULTS,
):
    filters = {
        "kind": kind,
        "is_alcoholic": alcoholic,
        "service_area": _area(service_area),
        "max_price": max_price,
    }
    filters = {key: value for key, value in filters.items() if value is not None}
    items = _filtered(ItemFilter, filters, catalog.public_items())
    packages = _filtered(PackageFilter, filters, catalog.public_packages())
    limit = max(1, min(int(limit), MAX_RESULTS))
    query = str(query or "").strip()
    results = _pick(
        _match(items, query, ""), _match(packages, query, "package_items__item__"), limit
    )
    if results:
        return {"results": results}
    return {
        "results": [],
        "note": "Nothing matches. Say it is not available.",
        "alternatives": _pick(items, packages, 5),
    }


def _match(queryset, query, prefix):
    """The whole phrase first, then any of its words, also in category names."""
    if not query:
        return queryset
    for words in ([query], [w for w in re.findall(r"\w+", query) if len(w) > 2]):
        condition = Q()
        for word in words:
            condition |= Q(name__icontains=word) | Q(description__icontains=word)
            for language in ("en", "sw"):
                condition |= Q(**{f"{prefix}category__name_{language}__icontains": word})
        # By id: the package join can repeat rows.
        ids = queryset.filter(condition).order_by().values("pk") if words else []
        found = queryset.filter(pk__in=ids)
        if found.exists():
            return found
    return queryset.none()


def _pick(items, packages, limit):
    """Up to `limit` results, with room for packages next to many items."""
    items, packages = list(items[:limit]), list(packages[:limit])
    keep = min(len(packages), max(limit // 2, limit - len(items)))
    return [_product(p) for p in [*items[: limit - keep], *packages[:keep]]]


def _product(product) -> dict:
    package = isinstance(product, Package)
    return {
        "id": str(product.pk),
        "type": "package" if package else "item",
        "name": product.name,
        "vendor": product.vendor.business_name,
        "vendor_id": str(product.vendor_id),
        "unit": product.pricing if package else product.unit,
        "price": format_tzs(product.price if package else product.unit_price),
        "min_quantity": product.min_guests if package else product.min_quantity,
        "alcoholic": product.contains_alcohol if package else product.is_alcoholic,
    }


def get_item_details(ctx, item_id=None, package_id=None):
    if bool(item_id) == bool(package_id):
        raise ToolError("Give either item_id or package_id.")
    products = catalog.public_items() if item_id else catalog.public_packages()
    product = products.filter(pk=_uuid(item_id or package_id)).first()
    if product is None:
        raise ToolError("This is not available. Search again.")
    details = _product(product) | {
        "description": product.description,
        "available": True,
        "vendor_min_notice_days": product.vendor.min_notice_days,
    }
    if package_id:
        details["contains"] = [str(entry) for entry in product.package_items.all()]
    return details


def list_vendors(ctx, service_area=None, offers=None):
    filters = {}
    if service_area:
        filters["service_area"] = _area(service_area)
    if offers in ("food", "drinks"):
        filters[f"offers_{offers}"] = True
    vendors = _filtered(VendorFilter, filters, public_vendors())
    return {
        "vendors": [
            {
                "id": str(vendor.pk),
                "name": vendor.business_name,
                "areas": [area.name for area in vendor.service_areas.all()],
                "min_notice_days": vendor.min_notice_days,
            }
            for vendor in vendors.prefetch_related("service_areas")[:20]
        ]
    }


def list_service_areas(ctx):
    return {"areas": list(ServiceArea.objects.values_list("name", flat=True))}


def _area(name):
    if not name:
        return None
    areas = ServiceArea.objects.filter(name__icontains=str(name).strip())
    area = areas.filter(name__iexact=str(name).strip()).first() or areas.first()
    if area is None:
        known = ", ".join(ServiceArea.objects.values_list("name", flat=True))
        raise ToolError(f"Unknown service area. Known areas: {known or 'none'}.")
    return area.pk


def _filtered(filterset, data, queryset):
    result = filterset(data, queryset=queryset)
    if not result.is_valid():
        raise ValidationError({field: list(errors) for field, errors in result.errors.items()})
    return result.qs


def _uuid(value):
    try:
        return UUID(str(value))
    except ValueError:
        raise ToolError("That id is not valid. Use an id returned by a tool.") from None


# --- Account and event -----------------------------------------------------


def register_client(ctx, full_name="", preferred_language=None, **_ignored):
    conversation = ctx.conversation
    if conversation.user is None:
        phone = conversation.phone
        if phone is None:
            raise ToolError(
                "The user's phone number is hidden, so an account cannot be made here. A number "
                "typed in chat cannot be used. They can book in the app instead."
            )
        full_name = str(full_name).replace("\x00", "").strip()[:150]
        if not full_name:
            raise ToolError("Ask the user for their full name.")
        if preferred_language not in User.Language.values:
            preferred_language = conversation.language
        try:
            conversation.user = create_client(
                phone=phone,
                full_name=full_name,
                password=None,
                preferred_language=preferred_language,
                created_via=User.CreatedVia.WHATSAPP,
            )
        except IntegrityError:  # registered through the API a moment ago
            conversation.user = User.objects.get(phone=phone)
        conversation.save(update_fields=["user", "updated_at"])
    return {"user_id": str(conversation.user.pk), "full_name": conversation.user.full_name}


def create_event(ctx, service_area=None, **args):
    client = ctx.client
    fields = ("event_type", "title", "starts_at", "venue", "guest_count")
    data = {name: args[name] for name in fields if name in args}
    data["service_area"] = _area(service_area)
    serializer = EventSerializer(data=data)
    serializer.is_valid(raise_exception=True)
    values = serializer.validated_data
    event = (
        events_for(client)
        .filter(title__iexact=values["title"], starts_at=values["starts_at"])
        .first()
    )
    if event is None:
        event = serializer.save(client=client)
    return {
        "event_id": str(event.pk),
        "title": event.title,
        "starts_at": f"{timezone.localtime(event.starts_at):%Y-%m-%d %H:%M}",
        "venue": event.venue,
        "guest_count": event.guest_count,
    }


# --- Orders ----------------------------------------------------------------


def _order_data(args):
    allowed = {k: args[k] for k in ("event_id", "vendor_id", "lines", "age_confirmed") if k in args}
    serializer = OrderCreateSerializer(data=allowed)
    serializer.is_valid(raise_exception=True)
    data = dict(serializer.validated_data)
    age_confirmed = data.pop("age_confirmed")
    data.pop("notes")
    data["lines"] = [dict(line) for line in data["lines"]]
    return data, age_confirmed


def _fingerprint(data, lines) -> str:
    """Same event, vendor, lines and prices give the same value."""
    lines = sorted(
        [str(line.item_id or line.package_id), line.quantity, str(line.unit_price_snapshot)]
        for line in lines
    )
    key = json.dumps([str(data["event_id"]), str(data["vendor_id"]), lines])
    return hashlib.sha256(key.encode()).hexdigest()


def _save_state(conversation, **changes):
    conversation.state = {**conversation.state, **changes}
    conversation.save(update_fields=["state", "updated_at"])


def quote_order(ctx, **args):
    client = ctx.client
    data, _age = _order_data(args)
    quote = orders.quote_order(client=client, **data)
    fingerprint = _fingerprint(data, quote.lines)
    # Quoting the same thing again must not cancel what the user is confirming.
    if not _was_shown(ctx, fingerprint):
        _save_state(
            ctx.conversation,
            quote={"fingerprint": fingerprint, "message_id": ctx.inbound.pk},
        )
    return {
        "vendor": quote.vendor.business_name,
        "lines": [
            {
                "name": line.name_snapshot,
                "quantity": line.quantity,
                "unit": line.unit_snapshot,
                "unit_price": format_tzs(line.unit_price_snapshot),
                "line_total": format_tzs(line.line_total),
            }
            for line in quote.lines
        ],
        "total": format_tzs(quote.total),
        "age_confirmation_required": quote.contains_alcohol,
    }


def _was_shown(ctx, fingerprint) -> bool:
    """The model's reply to the quoting message reached the user before they wrote this one."""
    pending = ctx.conversation.state.get("quote") or {}
    if pending.get("fingerprint") != fingerprint:
        return False
    return ChatMessage.objects.filter(
        conversation=ctx.conversation,
        reply_to_id=pending["message_id"],
        role=ChatMessage.Role.MODEL,
        status=ChatMessage.Status.SENT,
        payload__isnull=False,
        pk__lt=ctx.inbound.pk,
    ).exists()


def create_order(ctx, **args):
    client = ctx.client
    data, age_confirmed = _order_data(args)
    fingerprint = _fingerprint(data, orders.quote_order(client=client, **data).lines)
    last = ctx.conversation.state.get("last_order") or {}
    if (last.get("fingerprint"), last.get("message_id")) == (fingerprint, ctx.inbound.pk):
        return _order(ctx.order(last["reference"]))  # this message already placed it
    if not _was_shown(ctx, fingerprint):
        raise ToolError(
            "Not booked. Call quote_order with the same values, show the user the total, and book "
            "only after they confirm in their next message."
        )
    # Together, so a worker that dies and starts again cannot book twice.
    with transaction.atomic():
        order = orders.create_order(
            client=client, age_confirmed=age_confirmed, channel=Order.Channel.WHATSAPP, **data
        )
        # A vendor may have changed a price since the check above.
        if _fingerprint(data, order.lines.all()) != fingerprint:
            raise ToolError("Not booked: a price has just changed. Call quote_order again.")
        _save_state(
            ctx.conversation,
            quote=None,
            last_order={
                "fingerprint": fingerprint,
                "message_id": ctx.inbound.pk,
                "reference": order.reference,
            },
        )
    return _order(order)


def get_order_status(ctx, order_reference=None):
    if order_reference:
        return {"orders": [_order(ctx.order(order_reference))]}
    return {"orders": [_order(order) for order in _own_orders(ctx.client)[:5]]}


def cancel_order(ctx, order_reference=None):
    client = ctx.client
    return _order(orders.transition(ctx.order(order_reference), Order.Status.CANCELLED, client))


def _own_orders(client):
    # Not orders_for(): that shows vendors and admins other people's orders.
    return Order.objects.select_related("vendor", "event", "client").filter(client=client)


def _order(order) -> dict:
    date = f"{timezone.localtime(order.event.starts_at):%Y-%m-%d %H:%M}" if order.event else None
    return {
        "reference": order.reference,
        "status": order.status,
        "total": format_tzs(order.total),
        "vendor": order.vendor.business_name,
        "event_date": date,
    }


# --- Payment ---------------------------------------------------------------


def start_payment(ctx, order_reference=None, method=None, provider=None, phone=None):
    client = ctx.client
    order = ctx.order(order_reference)
    if method == "cash":
        data = {"method": Payment.Method.CASH}
    elif method == "mobile_money" and provider in MOBILE_PROVIDERS:
        data = {
            "method": Payment.Method.ONLINE,
            "provider": provider,
            "phone": phone or client.phone,
        }
    else:
        raise ToolError(
            f"Method must be cash, or mobile_money with one of: {', '.join(MOBILE_PROVIDERS)}."
        )
    serializer = PaySerializer(data=data)
    serializer.is_valid(raise_exception=True)
    payment = payments.start_payment(order, **serializer.validated_data)
    cash = payment.method == Payment.Method.CASH
    return {
        "payment_status": payment.status,
        "order_status": payment.order.status,
        "amount": format_tzs(payment.amount),
        "next": "Pay the vendor in cash; the vendor then confirms it."
        if cash
        else "Approve the request on the phone. The user is told when the result arrives.",
    }


# --- Declarations ----------------------------------------------------------

STRING, INTEGER, BOOLEAN = {"type": "string"}, {"type": "integer"}, {"type": "boolean"}


def _one_of(*values):
    return {"type": "string", "enum": list(values)}


def _declare(name, description, required=(), **properties):
    return {
        "name": name,
        "description": description,
        "parameters": {
            "type": "object",
            "properties": properties,
            "required": list(required),
        },
    }


LINES = {
    "type": "array",
    "description": "Each line has either item_id or package_id. "
    "For per_guest packages, quantity is the number of guests.",
    "items": {
        "type": "object",
        "properties": {"item_id": STRING, "package_id": STRING, "quantity": INTEGER},
        "required": ["quantity"],
    },
}
ORDER = {"event_id": STRING, "vendor_id": STRING, "lines": LINES}

DECLARATIONS = [
    _declare(
        "search_catalog",
        "Search available food, drinks and packages with their prices.",
        query={"type": "string", "description": "Name or kind of food or drink, e.g. soda"},
        kind=_one_of("food", "drink"),
        alcoholic=BOOLEAN,
        service_area=STRING,
        max_price={"type": "number", "description": "Highest unit price in TZS"},
        limit=INTEGER,
    ),
    _declare(
        "get_item_details",
        "Full details of one item or package.",
        item_id=STRING,
        package_id=STRING,
    ),
    _declare(
        "list_vendors",
        "Vendors, optionally by area or by what they offer.",
        service_area=STRING,
        offers=_one_of("food", "drinks"),
    ),
    _declare("list_service_areas", "Names of the areas served."),
    _declare(
        "register_client",
        "Create the sender's account. Their phone number is already known.",
        ["full_name", "preferred_language"],
        full_name=STRING,
        preferred_language=_one_of("en", "sw"),
    ),
    _declare(
        "create_event",
        "Save the sender's event.",
        ["event_type", "title", "starts_at", "venue", "guest_count"],
        event_type=_one_of(*Event.Type.values),
        title=STRING,
        starts_at={"type": "string", "description": "ISO 8601, East Africa Time"},
        venue=STRING,
        guest_count=INTEGER,
        service_area=STRING,
    ),
    _declare(
        "quote_order",
        "Check an order and get its total without booking. Always call this before create_order.",
        ["event_id", "vendor_id", "lines"],
        **ORDER,
    ),
    _declare(
        "create_order",
        "Book the order the user has just confirmed, with the values given to quote_order.",
        ["event_id", "vendor_id", "lines", "age_confirmed"],
        **ORDER,
        age_confirmed={
            "type": "boolean",
            "description": "True only if the user said they are 18 or older",
        },
    ),
    _declare(
        "start_payment",
        "Start paying a confirmed order.",
        ["order_reference", "method"],
        order_reference=STRING,
        method=_one_of("mobile_money", "cash"),
        provider=_one_of(*MOBILE_PROVIDERS),
        phone={"type": "string", "description": "Paying phone; default is the sender's"},
    ),
    _declare(
        "get_order_status",
        "Status of one of the sender's orders, or of their latest orders.",
        order_reference=STRING,
    ),
    _declare(
        "cancel_order",
        "Cancel the sender's unpaid order. Ask them to confirm first.",
        ["order_reference"],
        order_reference=STRING,
    ),
]

TOOLS = {
    function.__name__: function
    for function in (
        search_catalog,
        get_item_details,
        list_vendors,
        list_service_areas,
        register_client,
        create_event,
        quote_order,
        create_order,
        start_payment,
        get_order_status,
        cancel_order,
    )
}

"""Catalog business logic shared by REST views (and later the WhatsApp assistant)."""

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.db.models import Exists, OuterRef, Prefetch, Q, RestrictedError
from django.utils.translation import gettext as _
from rest_framework.exceptions import ValidationError

from apps.common.exceptions import Conflict
from apps.common.models import ascending_ids
from apps.vendors.services import public_vendors

from .models import Item, Package, PackageItem

# --- Queries ---------------------------------------------------------------


def items_queryset():
    return Item.objects.select_related("vendor", "category")


def packages_queryset():
    """Packages with their items and a `contains_alcohol` annotation."""
    alcoholic = PackageItem.objects.filter(package=OuterRef("pk"), item__is_alcoholic=True)
    return (
        Package.objects.select_related("vendor")
        .prefetch_related(
            Prefetch("package_items", queryset=PackageItem.objects.select_related("item"))
        )
        .annotate(contains_alcohol=Exists(alcoholic))
    )


def public_items():
    return items_queryset().filter(is_available=True, vendor__in=public_vendors())


def public_packages():
    return packages_queryset().filter(is_available=True, vendor__in=public_vendors())


def filter_by_text(queryset, text: str):
    return queryset.filter(Q(name__icontains=text) | Q(description__icontains=text))


def search_items(text: str):
    return filter_by_text(public_items(), text)


def search_packages(text: str):
    return filter_by_text(public_packages(), text)


# --- Writes ----------------------------------------------------------------


def save_item(item: Item, **changes) -> Item:
    """Create or update `item`, validating the resulting (merged) state."""
    for field, value in changes.items():
        setattr(item, field, value)
    try:
        item.clean()
    except DjangoValidationError as exc:
        raise ValidationError(exc.message_dict) from exc
    item.save()
    return item


def delete_item(item: Item) -> None:
    try:
        with transaction.atomic():
            item.delete()
    except RestrictedError as exc:
        raise Conflict(
            _("This item is part of a package. Remove it from the package first."),
            code="item_in_use",
        ) from exc


@transaction.atomic
def save_package(package: Package, *, items: list[dict] | None = None, **changes) -> Package:
    """Create or update `package`. `items` replaces its contents; None leaves them unchanged.

    Each entry is `{"item": Item, "quantity_note": str}`.
    """
    for field, value in changes.items():
        setattr(package, field, value)

    if items is not None:
        _validate_package_items(package, items)
    package.save()
    if items is not None:
        package.package_items.all().delete()
        # One by one with ascending ids, so (created_at, id) keeps the given order.
        for entry, pk in zip(items, ascending_ids(len(items)), strict=True):
            PackageItem.objects.create(
                pk=pk,
                package=package,
                item=entry["item"],
                quantity_note=entry.get("quantity_note", ""),
            )
    return packages_queryset().get(pk=package.pk)


def _validate_package_items(package, items):
    if not items:
        raise ValidationError({"items": _("A package needs at least one item.")})
    item_ids = [entry["item"].pk for entry in items]
    if len(set(item_ids)) != len(item_ids):
        raise ValidationError({"items": _("Each item can appear only once in a package.")})
    for entry in items:
        try:
            PackageItem(package=package, item=entry["item"]).clean()
        except DjangoValidationError as exc:
            raise ValidationError({"items": exc.messages}) from exc

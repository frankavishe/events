from decimal import Decimal

from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.common.models import BaseModel
from apps.common.money import CENT, MONEY_DECIMAL_PLACES, MONEY_MAX_DIGITS


class Kind(models.TextChoices):
    FOOD = "food", _("Food")
    DRINK = "drink", _("Drink")


class PriceField(models.DecimalField):
    """TZS amount greater than zero."""

    def __init__(self, *args, **kwargs):
        kwargs.setdefault("max_digits", MONEY_MAX_DIGITS)
        kwargs.setdefault("decimal_places", MONEY_DECIMAL_PLACES)
        kwargs.setdefault("validators", [MinValueValidator(CENT)])
        super().__init__(*args, **kwargs)


class Category(BaseModel):
    name_en = models.CharField(max_length=100)
    name_sw = models.CharField(max_length=100)
    kind = models.CharField(max_length=5, choices=Kind.choices)
    slug = models.SlugField(unique=True)

    class Meta:
        ordering = ("kind", "name_en")
        verbose_name_plural = "categories"

    def __str__(self):
        return self.name_en


class Item(BaseModel):
    class Unit(models.TextChoices):
        PLATE = "plate", _("Plate")
        PERSON = "person", _("Person")
        PIECE = "piece", _("Piece")
        BOTTLE = "bottle", _("Bottle")
        CRATE = "crate", _("Crate")
        LITRE = "litre", _("Litre")
        KG = "kg", _("Kg")
        TRAY = "tray", _("Tray")

    vendor = models.ForeignKey(
        "vendors.VendorProfile", on_delete=models.CASCADE, related_name="items"
    )
    category = models.ForeignKey(Category, on_delete=models.PROTECT, related_name="items")
    name = models.CharField(max_length=150)
    description = models.TextField(blank=True)
    kind = models.CharField(max_length=5, choices=Kind.choices)
    is_alcoholic = models.BooleanField(default=False)
    unit = models.CharField(max_length=10, choices=Unit.choices)
    unit_price = PriceField()
    min_quantity = models.PositiveIntegerField(default=1, validators=[MinValueValidator(1)])
    is_available = models.BooleanField(default=True)
    image = models.ImageField(upload_to="items/", blank=True)

    class Meta:
        ordering = ("name", "id")
        indexes = [
            models.Index(fields=["vendor", "is_available"]),
            models.Index(fields=["kind", "is_alcoholic"]),
        ]
        constraints = [
            models.CheckConstraint(
                name="catalog_item_food_not_alcoholic",
                condition=~models.Q(kind="food", is_alcoholic=True),
            ),
            models.CheckConstraint(
                name="catalog_item_price_positive",
                condition=models.Q(unit_price__gt=Decimal("0")),
            ),
            models.CheckConstraint(
                name="catalog_item_min_quantity_positive",
                condition=models.Q(min_quantity__gte=1),
            ),
        ]

    def __str__(self):
        return self.name

    def clean(self):
        """Cross-field rules, shared by the API services and the admin."""
        errors = {}
        if self.kind == Kind.FOOD and self.is_alcoholic:
            errors["is_alcoholic"] = _("Only drinks can be alcoholic.")
        if self.category_id and self.kind and self.category.kind != self.kind:
            errors["category"] = _("The category must be of the same kind as the item.")
        if errors:
            raise ValidationError(errors)


class Package(BaseModel):
    class Pricing(models.TextChoices):
        PER_GUEST = "per_guest", _("Per guest")
        FLAT = "flat", _("Flat")

    vendor = models.ForeignKey(
        "vendors.VendorProfile", on_delete=models.CASCADE, related_name="packages"
    )
    name = models.CharField(max_length=150)
    description = models.TextField(blank=True)
    pricing = models.CharField(max_length=10, choices=Pricing.choices)
    price = PriceField()
    min_guests = models.PositiveIntegerField(default=1, validators=[MinValueValidator(1)])
    is_available = models.BooleanField(default=True)

    class Meta:
        ordering = ("name", "id")
        indexes = [models.Index(fields=["vendor", "is_available"])]
        constraints = [
            models.CheckConstraint(
                name="catalog_package_price_positive",
                condition=models.Q(price__gt=Decimal("0")),
            ),
            models.CheckConstraint(
                name="catalog_package_min_guests_positive",
                condition=models.Q(min_guests__gte=1),
            ),
        ]

    def __str__(self):
        return self.name


class PackageItem(BaseModel):
    package = models.ForeignKey(Package, on_delete=models.CASCADE, related_name="package_items")
    # RESTRICT: an item in use cannot be deleted alone, but deleting its vendor removes both.
    item = models.ForeignKey(Item, on_delete=models.RESTRICT, related_name="package_items")
    quantity_note = models.CharField(max_length=100, blank=True)

    class Meta:
        ordering = ("created_at", "id")
        constraints = [
            models.UniqueConstraint(
                fields=["package", "item"], name="catalog_packageitem_unique_item"
            )
        ]

    def __str__(self):
        return f"{self.item} ({self.quantity_note})" if self.quantity_note else str(self.item)

    def clean(self):
        if self.item_id and self.item.vendor_id != self.package.vendor_id:
            raise ValidationError({"item": _("Packages can only contain the vendor's own items.")})

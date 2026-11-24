from django.utils.translation import gettext_lazy as _
from rest_framework import serializers
from rest_framework.fields import empty

from apps.vendors.serializers import VendorSummarySerializer

from . import services
from .models import Category, Item, Kind, Package, PackageItem


class ExplicitBooleanField(serializers.BooleanField):
    """A missing value stays missing in multipart forms too (DRF would default it to False)."""

    default_empty_html = empty


class CategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = Category
        fields = ("id", "slug", "name_en", "name_sw", "kind")


class ItemSerializer(serializers.ModelSerializer):
    vendor = VendorSummarySerializer(read_only=True)
    is_alcoholic = ExplicitBooleanField(
        required=False, help_text=_("Required for drinks; must be false for food.")
    )
    is_available = ExplicitBooleanField(required=False)

    class Meta:
        model = Item
        fields = (
            "id",
            "vendor",
            "category",
            "name",
            "description",
            "kind",
            "is_alcoholic",
            "unit",
            "unit_price",
            "min_quantity",
            "is_available",
            "image",
            "created_at",
        )
        read_only_fields = ("id", "created_at")

    def validate(self, attrs):
        becomes_drink = attrs.get("kind") == Kind.DRINK and (
            self.instance is None or self.instance.kind != Kind.DRINK
        )
        if becomes_drink and "is_alcoholic" not in attrs:
            raise serializers.ValidationError(
                {"is_alcoholic": _("State whether the drink is alcoholic.")}
            )
        return attrs

    def create(self, validated_data):
        return services.save_item(Item(), **validated_data)

    def update(self, instance, validated_data):
        return services.save_item(instance, **validated_data)


class PackageItemDetailSerializer(serializers.ModelSerializer):
    class Meta:
        model = Item
        fields = ("id", "name", "kind", "is_alcoholic", "unit")


class PackageItemSerializer(serializers.ModelSerializer):
    item_id = serializers.PrimaryKeyRelatedField(
        source="item", queryset=Item.objects.all(), write_only=True
    )
    item = PackageItemDetailSerializer(read_only=True)

    class Meta:
        model = PackageItem
        fields = ("item_id", "item", "quantity_note")


class PackageSerializer(serializers.ModelSerializer):
    vendor = VendorSummarySerializer(read_only=True)
    items = PackageItemSerializer(source="package_items", many=True)
    contains_alcohol = serializers.BooleanField(read_only=True)
    is_available = ExplicitBooleanField(required=False)

    class Meta:
        model = Package
        fields = (
            "id",
            "vendor",
            "name",
            "description",
            "pricing",
            "price",
            "min_guests",
            "is_available",
            "contains_alcohol",
            "items",
            "created_at",
        )
        read_only_fields = ("id", "created_at")

    def create(self, validated_data):
        items = validated_data.pop("package_items")
        return services.save_package(Package(), items=items, **validated_data)

    def update(self, instance, validated_data):
        items = validated_data.pop("package_items", None)
        return services.save_package(instance, items=items, **validated_data)

import django_filters as filters
from django.db.models import Exists, OuterRef

from apps.vendors.models import ServiceArea, VendorProfile

from . import services
from .models import Category, Item, Kind, Package, PackageItem


class CategoryFilter(filters.FilterSet):
    class Meta:
        model = Category
        fields = ("kind",)


class _CatalogFilter(filters.FilterSet):
    vendor = filters.ModelChoiceFilter(queryset=VendorProfile.objects.all())
    # One service area per request, so the M2M join cannot duplicate rows.
    service_area = filters.ModelChoiceFilter(
        field_name="vendor__service_areas", queryset=ServiceArea.objects.all()
    )
    search = filters.CharFilter(method="filter_search")

    def filter_search(self, queryset, name, value):
        return services.filter_by_text(queryset, value)


class ItemFilter(_CatalogFilter):
    kind = filters.ChoiceFilter(choices=Kind.choices)
    category = filters.ModelChoiceFilter(queryset=Category.objects.all(), to_field_name="slug")
    min_price = filters.NumberFilter(field_name="unit_price", lookup_expr="gte")
    max_price = filters.NumberFilter(field_name="unit_price", lookup_expr="lte")

    class Meta:
        model = Item
        fields = ("kind", "is_alcoholic", "category", "vendor")


class PackageFilter(_CatalogFilter):
    """`kind` and `category` match packages containing at least one such item."""

    kind = filters.ChoiceFilter(choices=Kind.choices, method="filter_item")
    category = filters.ModelChoiceFilter(
        queryset=Category.objects.all(), to_field_name="slug", method="filter_item"
    )
    is_alcoholic = filters.BooleanFilter(field_name="contains_alcohol")
    min_price = filters.NumberFilter(field_name="price", lookup_expr="gte")
    max_price = filters.NumberFilter(field_name="price", lookup_expr="lte")

    class Meta:
        model = Package
        fields = ("vendor",)

    def filter_item(self, queryset, name, value):
        matching = PackageItem.objects.filter(package=OuterRef("pk"), **{f"item__{name}": value})
        return queryset.filter(Exists(matching))

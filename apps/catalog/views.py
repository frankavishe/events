from django_filters.rest_framework import DjangoFilterBackend
from drf_spectacular.utils import extend_schema
from rest_framework import generics, viewsets
from rest_framework.filters import OrderingFilter
from rest_framework.permissions import SAFE_METHODS, AllowAny

from apps.common.permissions import IsApprovedVendor, IsVendor

from . import services
from .filters import CategoryFilter, ItemFilter, PackageFilter
from .models import Category, Item, Package
from .serializers import CategorySerializer, ItemSerializer, PackageSerializer

# --- Public ----------------------------------------------------------------


@extend_schema(tags=["catalog"])
class CategoryListView(generics.ListAPIView):
    queryset = Category.objects.all()
    serializer_class = CategorySerializer
    permission_classes = [AllowAny]
    filter_backends = [DjangoFilterBackend]
    filterset_class = CategoryFilter


class _PublicCatalogViewSet(viewsets.ReadOnlyModelViewSet):
    permission_classes = [AllowAny]
    filter_backends = [DjangoFilterBackend, OrderingFilter]


@extend_schema(tags=["catalog"])
class PublicItemViewSet(_PublicCatalogViewSet):
    """Available items from approved vendors."""

    queryset = Item.objects.none()  # for schema generation
    serializer_class = ItemSerializer
    filterset_class = ItemFilter
    ordering_fields = ("unit_price", "name", "created_at")

    def get_queryset(self):
        return services.public_items()


@extend_schema(tags=["catalog"])
class PublicPackageViewSet(_PublicCatalogViewSet):
    """Available packages from approved vendors."""

    queryset = Package.objects.none()  # for schema generation
    serializer_class = PackageSerializer
    filterset_class = PackageFilter
    ordering_fields = ("price", "name", "created_at")

    def get_queryset(self):
        return services.public_packages()


# --- Vendor ----------------------------------------------------------------


class _VendorCatalogViewSet(viewsets.ModelViewSet):
    """Own records only. Any vendor may read; only approved vendors may write."""

    http_method_names = ["get", "post", "patch", "delete", "head", "options"]
    filter_backends = [OrderingFilter]

    def get_permissions(self):
        read = self.request is None or self.request.method in SAFE_METHODS
        return [IsVendor()] if read else [IsApprovedVendor()]

    def perform_create(self, serializer):
        serializer.save(vendor=self.request.user.vendor_profile)


@extend_schema(tags=["vendor catalog"])
class VendorItemViewSet(_VendorCatalogViewSet):
    queryset = Item.objects.none()  # for schema generation
    serializer_class = ItemSerializer
    ordering_fields = ("unit_price", "name", "created_at")

    def get_queryset(self):
        return services.items_queryset().filter(vendor__user=self.request.user)

    def perform_destroy(self, instance):
        services.delete_item(instance)


@extend_schema(tags=["vendor catalog"])
class VendorPackageViewSet(_VendorCatalogViewSet):
    queryset = Package.objects.none()  # for schema generation
    serializer_class = PackageSerializer
    ordering_fields = ("price", "name", "created_at")

    def get_queryset(self):
        return services.packages_queryset().filter(vendor__user=self.request.user)

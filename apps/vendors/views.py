from django.shortcuts import get_object_or_404
from django_filters.rest_framework import DjangoFilterBackend
from drf_spectacular.utils import extend_schema
from rest_framework import generics, status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.serializers import UserSerializer
from apps.accounts.services import tokens_for
from apps.common.permissions import IsAdmin, IsVendor

from . import services
from .filters import VendorFilter
from .models import ServiceArea, VendorProfile
from .serializers import (
    PublicVendorSerializer,
    ServiceAreaSerializer,
    VendorProfileSerializer,
    VendorRegisterResponseSerializer,
    VendorRegisterSerializer,
)


class VendorRegisterView(APIView):
    """Register a vendor (pending approval) and return JWT tokens."""

    permission_classes = [AllowAny]
    authentication_classes = []

    @extend_schema(
        request=VendorRegisterSerializer,
        responses={201: VendorRegisterResponseSerializer},
        tags=["auth"],
    )
    def post(self, request):
        serializer = VendorRegisterSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        vendor = serializer.save()
        body = {
            "user": UserSerializer(vendor.user).data,
            "vendor": VendorProfileSerializer(vendor).data,
            **tokens_for(vendor.user),
        }
        return Response(body, status=status.HTTP_201_CREATED)


@extend_schema(tags=["vendors"])
class OwnVendorProfileView(generics.RetrieveUpdateAPIView):
    """The authenticated vendor's own profile, including payout details."""

    serializer_class = VendorProfileSerializer
    permission_classes = [IsVendor]
    http_method_names = ["get", "patch", "head", "options"]

    def get_object(self):
        return get_object_or_404(VendorProfile, user=self.request.user)


@extend_schema(tags=["vendors"])
class PublicVendorListView(generics.ListAPIView):
    """Approved vendors."""

    serializer_class = PublicVendorSerializer
    permission_classes = [AllowAny]
    filter_backends = [DjangoFilterBackend]
    filterset_class = VendorFilter

    def get_queryset(self):
        return services.public_vendors().prefetch_related("service_areas")


@extend_schema(tags=["vendors"])
class PublicVendorDetailView(generics.RetrieveAPIView):
    serializer_class = PublicVendorSerializer
    permission_classes = [AllowAny]

    def get_queryset(self):
        return services.public_vendors().prefetch_related("service_areas")


@extend_schema(tags=["vendors"])
class ServiceAreaListView(generics.ListAPIView):
    queryset = ServiceArea.objects.all()
    serializer_class = ServiceAreaSerializer
    permission_classes = [AllowAny]
    filter_backends = []


class _ModerateVendorView(APIView):
    permission_classes = [IsAdmin]

    def moderate(self, pk) -> VendorProfile:
        raise NotImplementedError

    @extend_schema(request=None, responses={200: VendorProfileSerializer}, tags=["admin"])
    def post(self, request, pk):
        return Response(VendorProfileSerializer(self.moderate(pk)).data)


class ApproveVendorView(_ModerateVendorView):
    """Approve a pending, rejected or suspended vendor."""

    def moderate(self, pk):
        return services.approve(pk, self.request.user)


class RejectVendorView(_ModerateVendorView):
    """Reject a pending vendor."""

    def moderate(self, pk):
        return services.reject(pk)


class SuspendVendorView(_ModerateVendorView):
    """Suspend an approved vendor; its catalog is hidden immediately."""

    def moderate(self, pk):
        return services.suspend(pk)

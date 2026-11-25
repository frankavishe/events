from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema
from rest_framework import generics, status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common.permissions import IsAdmin, IsVendor
from apps.vendors.models import VendorProfile

from . import services
from .models import CommissionSetting, Payout, VendorEarning
from .serializers import (
    AdminPayoutSerializer,
    CommissionInputSerializer,
    CommissionPageSerializer,
    CommissionSerializer,
    EarningPageSerializer,
    EarningSerializer,
    LedgerSummarySerializer,
    PayoutInputSerializer,
    VendorPayoutSerializer,
)


class _OwnLedgerView(generics.ListAPIView):
    """Any vendor status: a suspended vendor may still be owed money."""

    permission_classes = [IsVendor]
    filter_backends = []

    def vendor(self):
        return get_object_or_404(VendorProfile, user=self.request.user)


@extend_schema(tags=["ledger"])
class VendorEarningsView(_OwnLedgerView):
    """Your earnings per paid order, and totals over all of them."""

    queryset = VendorEarning.objects.none()  # for schema generation
    serializer_class = EarningSerializer

    def get_queryset(self):
        return self.vendor().earnings.select_related("order").order_by("-created_at", "id")

    @extend_schema(responses=EarningPageSerializer)
    def get(self, request, *args, **kwargs):
        response = super().get(request, *args, **kwargs)
        summary = services.vendor_summary(self.vendor())
        response.data["summary"] = LedgerSummarySerializer(summary).data
        return response


@extend_schema(tags=["ledger"])
class VendorPayoutsView(_OwnLedgerView):
    """Payouts made to you."""

    queryset = Payout.objects.none()  # for schema generation
    serializer_class = VendorPayoutSerializer

    def get_queryset(self):
        return self.vendor().payouts.order_by("-paid_at", "id")


@extend_schema(tags=["admin"])
class CommissionView(generics.ListAPIView):
    """Current commission rate and its history."""

    queryset = CommissionSetting.objects.select_related("set_by")
    serializer_class = CommissionSerializer
    permission_classes = [IsAdmin]
    filter_backends = []

    @extend_schema(responses=CommissionPageSerializer)
    def get(self, request, *args, **kwargs):
        response = super().get(request, *args, **kwargs)
        response.data["current_rate"] = f"{services.current_rate():.4f}"
        return response

    @extend_schema(request=CommissionInputSerializer, responses={201: CommissionSerializer})
    def post(self, request):
        """Set the rate for payments that succeed from now on."""
        serializer = CommissionInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        setting = services.set_rate(serializer.validated_data["rate"], request.user)
        return Response(CommissionSerializer(setting).data, status=status.HTTP_201_CREATED)


@extend_schema(tags=["admin"])
class AdminPayoutsView(generics.ListAPIView):
    """Payouts to all vendors."""

    queryset = Payout.objects.select_related("vendor", "recorded_by").order_by("-paid_at", "id")
    serializer_class = AdminPayoutSerializer
    permission_classes = [IsAdmin]
    filter_backends = []

    @extend_schema(request=PayoutInputSerializer, responses={201: AdminPayoutSerializer})
    def post(self, request):
        """Record a transfer made outside the system. It cannot exceed the vendor's balance."""
        serializer = PayoutInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        payout = services.record_payout(actor=request.user, **serializer.validated_data)
        return Response(AdminPayoutSerializer(payout).data, status=status.HTTP_201_CREATED)


class VendorBalanceView(APIView):
    """A vendor's totals and balance."""

    permission_classes = [IsAdmin]

    @extend_schema(responses=LedgerSummarySerializer, tags=["admin"])
    def get(self, request, pk):
        vendor = get_object_or_404(VendorProfile, pk=pk)
        return Response(LedgerSummarySerializer(services.vendor_summary(vendor)).data)

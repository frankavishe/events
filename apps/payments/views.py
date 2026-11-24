import logging
from decimal import Decimal, InvalidOperation
from uuid import UUID

from django.conf import settings
from django.http import Http404
from django.shortcuts import get_object_or_404
from django.utils.crypto import constant_time_compare
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema
from rest_framework import generics, status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common.permissions import IsAdmin, IsClient, IsVendor
from apps.orders.models import Order
from apps.orders.serializers import OrderSerializer
from apps.orders.services import orders_for
from apps.orders.views import order_response

from . import services
from .models import Payment
from .serializers import (
    PaymentSerializer,
    PayResponseSerializer,
    PaySerializer,
    RefundSerializer,
)

logger = logging.getLogger(__name__)


class PayOrderView(APIView):
    """Pay a confirmed order online (202, poll the payment) or choose cash (200)."""

    permission_classes = [IsClient]

    @extend_schema(
        request=PaySerializer,
        responses={200: PayResponseSerializer, 202: PayResponseSerializer},
        tags=["payments"],
    )
    def post(self, request, pk):
        order = get_object_or_404(orders_for(request.user), pk=pk)
        serializer = PaySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        payment = services.start_payment(order, **serializer.validated_data)
        cash = payment.method == Payment.Method.CASH
        return Response(
            PayResponseSerializer(payment).data,
            status=status.HTTP_200_OK if cash else status.HTTP_202_ACCEPTED,
        )


class ConfirmCashView(APIView):
    """The order's vendor or an admin confirms that cash was received."""

    permission_classes = [IsVendor | IsAdmin]

    @extend_schema(request=None, responses=OrderSerializer, tags=["payments"])
    def post(self, request, pk):
        # Not scoped: another vendor gets 403 here (spec), not 404.
        get_object_or_404(Order, pk=pk)
        return order_response(services.confirm_cash(pk, request.user))


class RefundOrderView(APIView):
    """Record a refund made outside the system; reverses the vendor's earning."""

    permission_classes = [IsAdmin]

    @extend_schema(request=RefundSerializer, responses=OrderSerializer, tags=["admin"])
    def post(self, request, pk):
        order = get_object_or_404(orders_for(request.user), pk=pk)
        serializer = RefundSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return order_response(
            services.refund(order, request.user, serializer.validated_data["note"])
        )


@extend_schema(tags=["payments"])
class PaymentDetailView(generics.RetrieveAPIView):
    """Poll a payment's status."""

    queryset = Payment.objects.none()  # for schema generation
    serializer_class = PaymentSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return services.payments_for(self.request.user)


class AzamPayCallbackView(APIView):
    """Payment results from AzamPay, authenticated by the secret token in the path.

    Anything understood or unusable gets 200, so the gateway does not keep retrying it.
    """

    permission_classes = [AllowAny]
    authentication_classes = []

    @extend_schema(
        request=OpenApiTypes.OBJECT, responses={200: OpenApiTypes.OBJECT}, tags=["webhooks"]
    )
    def post(self, request, token):
        expected = settings.AZAMPAY_CALLBACK_TOKEN
        if not expected or not constant_time_compare(token, expected):
            raise Http404
        self._process(request.data)
        return Response({"received": True})

    def _process(self, data):
        payload = data if isinstance(data, dict) else {}
        payment_id = _uuid(payload.get("utilityref"))
        outcome = str(payload.get("transactionstatus", "")).lower()
        if payment_id is None or outcome not in ("success", "failure"):
            logger.warning("AzamPay callback ignored: unusable reference or status")
            return
        payment = services.handle_gateway_result(
            payment_id,
            success=outcome == "success",
            amount=_decimal(payload.get("amount")),
            reference=str(payload.get("reference") or ""),
            raw=dict(payload.items()),
        )
        if payment is None:
            logger.warning("AzamPay callback for unknown payment %s", payment_id)


def _uuid(value) -> UUID | None:
    try:
        return UUID(str(value))
    except ValueError:
        return None


def _decimal(value) -> Decimal | None:
    if isinstance(value, bool) or not isinstance(value, str | int | float):
        return None
    try:
        amount = Decimal(str(value))
    except InvalidOperation:
        return None
    return amount if amount.is_finite() else None

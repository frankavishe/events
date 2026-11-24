from django_filters.rest_framework import DjangoFilterBackend
from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.filters import OrderingFilter
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.common.permissions import IsAdmin, IsClient, IsVendor

from . import services
from .filters import OrderFilter
from .models import Order
from .serializers import (
    DeclineSerializer,
    OrderCreateSerializer,
    OrderListSerializer,
    OrderSerializer,
)

Status = Order.Status


def order_response(order, code=status.HTTP_200_OK):
    """Full, freshly loaded order."""
    orders = Order.objects.select_related("event", "client", "vendor")
    fresh = services.with_details(orders).get(pk=order.pk)
    return Response(OrderSerializer(fresh).data, status=code)


@extend_schema(tags=["orders"])
@extend_schema_view(
    create=extend_schema(request=OrderCreateSerializer, responses={201: OrderSerializer})
)
class OrderViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    """Clients see their own orders, vendors the orders placed with them, admins all."""

    queryset = Order.objects.none()  # for schema generation
    filter_backends = [DjangoFilterBackend, OrderingFilter]
    filterset_class = OrderFilter
    ordering_fields = ("created_at", "total")
    permission_classes = [IsAuthenticated]

    def get_permissions(self):
        if self.action == "create":
            return [IsClient()]
        return super().get_permissions()

    def get_serializer_class(self):
        return OrderListSerializer if self.action == "list" else OrderSerializer

    def get_queryset(self):
        orders = services.orders_for(self.request.user)
        return services.with_details(orders) if self.action == "retrieve" else orders

    def create(self, request):
        """Place an order with one vendor for one of your events."""
        serializer = OrderCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        order = services.create_order(client=request.user, **serializer.validated_data)
        return order_response(order, status.HTTP_201_CREATED)

    def _move(self, to, note=""):
        order = services.transition(self.get_object(), to, self.request.user, note)
        return order_response(order)

    @extend_schema(request=None, responses=OrderSerializer)
    @action(detail=True, methods=["post"], permission_classes=[IsVendor | IsAdmin])
    def confirm(self, request, pk=None):
        return self._move(Status.CONFIRMED)

    @extend_schema(request=DeclineSerializer, responses=OrderSerializer)
    @action(detail=True, methods=["post"], permission_classes=[IsVendor | IsAdmin])
    def decline(self, request, pk=None):
        serializer = DeclineSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return self._move(Status.DECLINED, serializer.validated_data["reason"])

    @extend_schema(request=None, responses=OrderSerializer)
    @action(detail=True, methods=["post"], permission_classes=[IsClient | IsAdmin])
    def cancel(self, request, pk=None):
        return self._move(Status.CANCELLED)

    @extend_schema(request=None, responses=OrderSerializer)
    @action(detail=True, methods=["post"], permission_classes=[IsVendor | IsAdmin])
    def fulfil(self, request, pk=None):
        return self._move(Status.FULFILLED)

    @extend_schema(request=None, responses=OrderSerializer)
    @action(detail=True, methods=["post"], permission_classes=[IsVendor | IsAdmin])
    def complete(self, request, pk=None):
        """Only after the event date has passed."""
        return self._move(Status.COMPLETED)

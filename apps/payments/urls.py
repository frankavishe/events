from django.urls import path

from . import views

urlpatterns = [
    path("orders/<uuid:pk>/pay/", views.PayOrderView.as_view(), name="order-pay"),
    path(
        "orders/<uuid:pk>/confirm-cash/",
        views.ConfirmCashView.as_view(),
        name="order-confirm-cash",
    ),
    path("orders/<uuid:pk>/refund/", views.RefundOrderView.as_view(), name="order-refund"),
    path("payments/<uuid:pk>/", views.PaymentDetailView.as_view(), name="payment-detail"),
    path(
        "webhooks/azampay/<str:token>/",
        views.AzamPayCallbackView.as_view(),
        name="azampay-callback",
    ),
]

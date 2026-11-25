from django.urls import path

from . import views

urlpatterns = [
    path("vendor/earnings/", views.VendorEarningsView.as_view(), name="vendor-earnings"),
    path("vendor/payouts/", views.VendorPayoutsView.as_view(), name="vendor-payouts"),
    path("admin/commission/", views.CommissionView.as_view(), name="admin-commission"),
    path("admin/payouts/", views.AdminPayoutsView.as_view(), name="admin-payouts"),
    path(
        "admin/vendors/<uuid:pk>/balance/",
        views.VendorBalanceView.as_view(),
        name="admin-vendor-balance",
    ),
]

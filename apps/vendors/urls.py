from django.urls import path

from . import views

urlpatterns = [
    path("auth/register/vendor/", views.VendorRegisterView.as_view(), name="vendor-register"),
    path("vendor/profile/", views.OwnVendorProfileView.as_view(), name="vendor-profile"),
    path("vendors/", views.PublicVendorListView.as_view(), name="vendor-list"),
    path("vendors/<uuid:pk>/", views.PublicVendorDetailView.as_view(), name="vendor-detail"),
    path("service-areas/", views.ServiceAreaListView.as_view(), name="service-area-list"),
    path(
        "admin/vendors/<uuid:pk>/approve/",
        views.ApproveVendorView.as_view(),
        name="admin-vendor-approve",
    ),
    path(
        "admin/vendors/<uuid:pk>/reject/",
        views.RejectVendorView.as_view(),
        name="admin-vendor-reject",
    ),
    path(
        "admin/vendors/<uuid:pk>/suspend/",
        views.SuspendVendorView.as_view(),
        name="admin-vendor-suspend",
    ),
]

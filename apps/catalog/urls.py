from django.urls import path
from rest_framework.routers import SimpleRouter

from . import views

router = SimpleRouter()
router.register("items", views.PublicItemViewSet, basename="item")
router.register("packages", views.PublicPackageViewSet, basename="package")
router.register("vendor/items", views.VendorItemViewSet, basename="vendor-item")
router.register("vendor/packages", views.VendorPackageViewSet, basename="vendor-package")

urlpatterns = [
    path("categories/", views.CategoryListView.as_view(), name="category-list"),
    *router.urls,
]

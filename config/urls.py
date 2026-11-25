from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

api_v1 = [
    path("", include("apps.accounts.urls")),
    path("", include("apps.vendors.urls")),
    path("", include("apps.catalog.urls")),
    path("", include("apps.events.urls")),
    path("", include("apps.orders.urls")),
    path("", include("apps.payments.urls")),
    path("", include("apps.ledger.urls")),
    path("", include("apps.chatbot.urls")),
]

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/v1/", include(api_v1)),
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path("api/docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="docs"),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

from django.urls import path
from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework_simplejwt.views import TokenRefreshView

from .views import MeView, RegisterView, TokenObtainView

TaggedTokenRefreshView = extend_schema_view(post=extend_schema(tags=["auth"]))(TokenRefreshView)

urlpatterns = [
    path("auth/register/", RegisterView.as_view(), name="auth-register"),
    path("auth/token/", TokenObtainView.as_view(), name="auth-token"),
    path("auth/token/refresh/", TaggedTokenRefreshView.as_view(), name="auth-token-refresh"),
    path("me/", MeView.as_view(), name="me"),
]

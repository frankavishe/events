from drf_spectacular.utils import extend_schema
from rest_framework import generics, status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common.throttling import LoginAddressThrottle, LoginThrottle, RegisterThrottle

from . import services
from .serializers import (
    LoginTokenSerializer,
    RegisterResponseSerializer,
    RegisterSerializer,
    TokenPairSerializer,
    UserSerializer,
)


class RegisterView(APIView):
    """Register a client account and return JWT tokens."""

    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = [RegisterThrottle]

    @extend_schema(
        request=RegisterSerializer,
        responses={201: RegisterResponseSerializer},
        tags=["auth"],
    )
    def post(self, request):
        serializer = RegisterSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        body = {"user": UserSerializer(user).data, **services.tokens_for(user)}
        return Response(body, status=status.HTTP_201_CREATED)


class TokenObtainView(APIView):
    """Log in with phone or email + password; returns `{access, refresh}`."""

    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = [LoginAddressThrottle, LoginThrottle]

    def get_authenticate_header(self, request):
        # Without authenticators DRF would turn a failed login into 403 instead of 401.
        return 'Bearer realm="api"'

    @extend_schema(
        request=LoginTokenSerializer, responses={200: TokenPairSerializer}, tags=["auth"]
    )
    def post(self, request):
        serializer = LoginTokenSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return Response(serializer.validated_data)


@extend_schema(tags=["accounts"])
class MeView(generics.RetrieveUpdateAPIView):
    """The authenticated user's own profile."""

    serializer_class = UserSerializer
    permission_classes = [IsAuthenticated]
    http_method_names = ["get", "patch", "head", "options"]

    def get_object(self):
        return self.request.user

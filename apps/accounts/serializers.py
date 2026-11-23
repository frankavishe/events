from django.contrib.auth import password_validation
from django.contrib.auth.models import update_last_login
from django.utils.translation import gettext_lazy as _
from rest_framework import exceptions, serializers
from rest_framework_simplejwt.settings import api_settings as jwt_settings

from apps.common.phone import InvalidPhoneNumber, normalize_phone

from . import services
from .models import User


def _validate_unique_email(value, instance=None):
    if not value:
        return None
    value = value.strip().lower()
    qs = User.objects.filter(email__iexact=value)
    if instance is not None:
        qs = qs.exclude(pk=instance.pk)
    if qs.exists():
        raise serializers.ValidationError(_("A user with this email already exists."))
    return value


class UserSerializer(serializers.ModelSerializer):
    """Own profile. Phone, role and channel are read-only."""

    class Meta:
        model = User
        fields = (
            "id",
            "full_name",
            "phone",
            "email",
            "role",
            "preferred_language",
            "created_via",
            "created_at",
        )
        read_only_fields = ("id", "phone", "role", "created_via", "created_at")
        extra_kwargs = {"email": {"required": False, "allow_null": True, "allow_blank": True}}

    def validate_email(self, value):
        return _validate_unique_email(value, self.instance)


class RegisterSerializer(serializers.Serializer):
    full_name = serializers.CharField(max_length=150)
    phone = serializers.CharField(max_length=32)
    email = serializers.EmailField(required=False, allow_null=True, allow_blank=True)
    password = serializers.CharField(write_only=True, style={"input_type": "password"})
    preferred_language = serializers.ChoiceField(
        choices=User.Language.choices, default=User.Language.EN
    )

    def validate_phone(self, value):
        try:
            phone = normalize_phone(value)
        except InvalidPhoneNumber as exc:
            raise serializers.ValidationError(_("Enter a valid phone number.")) from exc
        if User.objects.filter(phone=phone).exists():
            raise serializers.ValidationError(_("A user with this phone number already exists."))
        return phone

    def validate_email(self, value):
        return _validate_unique_email(value)

    def validate(self, attrs):
        candidate = User(
            phone=attrs["phone"], full_name=attrs["full_name"], email=attrs.get("email")
        )
        try:
            password_validation.validate_password(attrs["password"], user=candidate)
        except Exception as exc:  # django ValidationError
            raise serializers.ValidationError({"password": list(exc.messages)}) from exc
        return attrs

    def create(self, validated_data):
        return services.register_client(**validated_data)


class RegisterResponseSerializer(serializers.Serializer):
    user = UserSerializer()
    access = serializers.CharField()
    refresh = serializers.CharField()


class LoginTokenSerializer(serializers.Serializer):
    """Obtain JWT pair with `login` = phone (any accepted format) or email."""

    login = serializers.CharField()
    password = serializers.CharField(write_only=True, style={"input_type": "password"})

    default_error_messages = {
        "no_active_account": _("No active account found with the given credentials."),
    }

    def validate(self, attrs):
        try:
            user = User.objects.get_by_login(attrs["login"])
        except (User.DoesNotExist, InvalidPhoneNumber):
            user = None

        if user is None or not user.check_password(attrs["password"]) or not user.is_active:
            if user is None:
                User().set_password(attrs["password"])  # equalize timing
            raise exceptions.AuthenticationFailed(
                self.error_messages["no_active_account"], "no_active_account"
            )

        if jwt_settings.UPDATE_LAST_LOGIN:
            update_last_login(None, user)
        self.user = user
        return services.tokens_for(user)


class TokenPairSerializer(serializers.Serializer):
    access = serializers.CharField()
    refresh = serializers.CharField()

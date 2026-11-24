import pytest
from django.contrib.auth import get_user_model

from tests.factories import AdminFactory, UserFactory, VendorUserFactory

pytestmark = pytest.mark.django_db

User = get_user_model()

REGISTER_URL = "/api/v1/auth/register/"
TOKEN_URL = "/api/v1/auth/token/"
REFRESH_URL = "/api/v1/auth/token/refresh/"
ME_URL = "/api/v1/me/"

STRONG_PASSWORD = "Chakula-Bora-2026"


def register_payload(**overrides):
    data = {
        "full_name": "Asha Mwinyi",
        "phone": "0712345678",
        "email": "asha@example.com",
        "password": STRONG_PASSWORD,
        "preferred_language": "sw",
    }
    data.update(overrides)
    return data


# --- User model ------------------------------------------------------------


class TestUserModel:
    def test_uuid_pk_and_defaults(self):
        user = User.objects.create_user(phone="+255712345678", full_name="A", password="x")
        assert user.pk.version == 4
        assert user.role == User.Role.CLIENT
        assert user.preferred_language == "en"
        assert user.created_via == User.CreatedVia.API
        assert user.created_at is not None

    def test_create_user_normalizes_phone(self):
        user = User.objects.create_user(phone="0712 345 678", full_name="A", password="x")
        assert user.phone == "+255712345678"

    def test_create_user_without_password_is_unusable(self):
        user = User.objects.create_user(
            phone="+255712345678", full_name="A", created_via=User.CreatedVia.WHATSAPP
        )
        assert not user.has_usable_password()

    def test_create_superuser_is_admin_role(self):
        user = User.objects.create_superuser(phone="+255712345678", full_name="A", password="x")
        assert user.is_staff and user.is_superuser
        assert user.role == User.Role.ADMIN

    def test_email_blank_stored_as_null(self):
        a = User.objects.create_user(phone="+255712345678", full_name="A", email="")
        b = User.objects.create_user(phone="+255712345679", full_name="B", email="")
        assert a.email is None and b.email is None

    def test_email_lowercased(self):
        user = User.objects.create_user(phone="+255712345678", full_name="A", email="X@Ex.COM")
        assert user.email == "x@ex.com"


# --- Registration ----------------------------------------------------------


class TestRegister:
    def test_register_client_returns_tokens(self, api_client):
        response = api_client.post(REGISTER_URL, register_payload(), format="json")
        assert response.status_code == 201, response.data
        body = response.json()
        assert body["access"] and body["refresh"]
        assert body["user"]["phone"] == "+255712345678"
        assert body["user"]["role"] == "client"
        assert body["user"]["preferred_language"] == "sw"
        assert "password" not in body["user"]
        user = User.objects.get(phone="+255712345678")
        assert user.check_password(STRONG_PASSWORD)
        assert user.created_via == User.CreatedVia.API

    def test_register_ignores_role_escalation(self, api_client):
        response = api_client.post(
            REGISTER_URL, register_payload(role="admin", is_staff=True), format="json"
        )
        assert response.status_code == 201
        user = User.objects.get(phone="+255712345678")
        assert user.role == User.Role.CLIENT
        assert not user.is_staff

    def test_email_is_optional(self, api_client):
        payload = register_payload()
        del payload["email"]
        response = api_client.post(REGISTER_URL, payload, format="json")
        assert response.status_code == 201

    def test_duplicate_phone_in_other_format_rejected(self, api_client):
        UserFactory(phone="+255712345678")
        response = api_client.post(
            REGISTER_URL, register_payload(phone="255712345678"), format="json"
        )
        assert response.status_code == 400
        assert "phone" in response.json()["errors"]

    def test_duplicate_email_case_insensitive_rejected(self, api_client):
        UserFactory(email="asha@example.com")
        response = api_client.post(
            REGISTER_URL, register_payload(email="ASHA@example.com"), format="json"
        )
        assert response.status_code == 400
        assert "email" in response.json()["errors"]

    def test_invalid_phone_rejected(self, api_client):
        response = api_client.post(REGISTER_URL, register_payload(phone="12345"), format="json")
        assert response.status_code == 400
        assert response.json()["code"] == "invalid"
        assert "phone" in response.json()["errors"]

    def test_weak_password_rejected(self, api_client):
        response = api_client.post(
            REGISTER_URL, register_payload(password="12345678"), format="json"
        )
        assert response.status_code == 400
        assert "password" in response.json()["errors"]

    def test_missing_required_fields(self, api_client):
        response = api_client.post(REGISTER_URL, {}, format="json")
        assert response.status_code == 400
        errors = response.json()["errors"]
        assert {"full_name", "phone", "password"} <= set(errors)

    def test_invalid_language_rejected(self, api_client):
        response = api_client.post(
            REGISTER_URL, register_payload(preferred_language="fr"), format="json"
        )
        assert response.status_code == 400
        assert "preferred_language" in response.json()["errors"]


# --- Token login -----------------------------------------------------------


class TestToken:
    @pytest.fixture
    def user(self):
        return UserFactory(
            phone="+255712345678", email="asha@example.com", password=STRONG_PASSWORD
        )

    @pytest.mark.parametrize(
        "login", ["+255712345678", "0712345678", "asha@example.com", "ASHA@example.com"]
    )
    def test_login_by_phone_or_email(self, api_client, user, login):
        response = api_client.post(
            TOKEN_URL, {"login": login, "password": STRONG_PASSWORD}, format="json"
        )
        assert response.status_code == 200, response.data
        assert set(response.json()) >= {"access", "refresh"}

    def test_wrong_password(self, api_client, user):
        response = api_client.post(
            TOKEN_URL, {"login": "0712345678", "password": "wrong"}, format="json"
        )
        assert response.status_code == 401
        assert "code" in response.json()

    def test_unknown_login(self, api_client, user):
        response = api_client.post(
            TOKEN_URL, {"login": "nobody@example.com", "password": STRONG_PASSWORD}, format="json"
        )
        assert response.status_code == 401

    def test_inactive_user_cannot_login(self, api_client, user):
        user.is_active = False
        user.save()
        response = api_client.post(
            TOKEN_URL, {"login": "0712345678", "password": STRONG_PASSWORD}, format="json"
        )
        assert response.status_code == 401

    def test_missing_fields(self, api_client):
        response = api_client.post(TOKEN_URL, {}, format="json")
        assert response.status_code == 400
        assert {"login", "password"} <= set(response.json()["errors"])

    def test_refresh(self, api_client, user):
        tokens = api_client.post(
            TOKEN_URL, {"login": "0712345678", "password": STRONG_PASSWORD}, format="json"
        ).json()
        response = api_client.post(REFRESH_URL, {"refresh": tokens["refresh"]}, format="json")
        assert response.status_code == 200
        assert response.json()["access"]

    def test_refresh_with_garbage_token(self, api_client):
        response = api_client.post(REFRESH_URL, {"refresh": "garbage"}, format="json")
        assert response.status_code == 401


# --- /me/ ------------------------------------------------------------------


class TestMe:
    def test_requires_auth(self, api_client):
        response = api_client.get(ME_URL)
        assert response.status_code == 401
        assert response.json()["code"] == "not_authenticated"

    @pytest.mark.parametrize("factory", [UserFactory, VendorUserFactory, AdminFactory])
    def test_get_own_profile_any_role(self, auth_client, factory):
        user = factory()
        response = auth_client(user).get(ME_URL)
        assert response.status_code == 200
        body = response.json()
        assert body["id"] == str(user.id)
        assert body["phone"] == user.phone
        assert body["role"] == user.role

    def test_patch_editable_fields(self, auth_client):
        user = UserFactory()
        response = auth_client(user).patch(
            ME_URL,
            {"full_name": "New Name", "email": "new@example.com", "preferred_language": "sw"},
            format="json",
        )
        assert response.status_code == 200, response.data
        user.refresh_from_db()
        assert user.full_name == "New Name"
        assert user.email == "new@example.com"
        assert user.preferred_language == "sw"

    def test_patch_cannot_change_phone_or_role(self, auth_client):
        user = UserFactory(phone="+255712345678")
        auth_client(user).patch(ME_URL, {"phone": "+255799999999", "role": "admin"}, format="json")
        user.refresh_from_db()
        assert user.phone == "+255712345678"
        assert user.role == User.Role.CLIENT

    def test_patch_email_taken_by_other(self, auth_client):
        UserFactory(email="taken@example.com")
        user = UserFactory()
        response = auth_client(user).patch(ME_URL, {"email": "Taken@example.com"}, format="json")
        assert response.status_code == 400
        assert "email" in response.json()["errors"]

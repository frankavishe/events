import json
from datetime import timedelta
from unittest.mock import patch

import pytest
from freezegun import freeze_time
from rest_framework_simplejwt.tokens import RefreshToken

from apps.accounts import services
from apps.accounts.models import PasswordCode, User
from apps.chatbot.models import ChatMessage, Conversation
from apps.notifications import tasks
from apps.notifications.clients import FakeMessagingClient, MessagingError
from tests.factories import (
    DEFAULT_PASSWORD,
    AdminFactory,
    ClientFactory,
    UserFactory,
    VendorUserFactory,
)

REQUEST = "/api/v1/auth/password/code/"
CONFIRM = "/api/v1/auth/password/"
TOKEN = "/api/v1/auth/token/"
REFRESH = "/api/v1/auth/token/refresh/"
ME = "/api/v1/me/"
NEW_PASSWORD = "Pilau-Tamu-2027"


@pytest.fixture(autouse=True)
def outbox(settings):
    settings.WHATSAPP_TEMPLATE_AUTH_CODE = "auth_code"
    FakeMessagingClient.reset()
    yield FakeMessagingClient.outbox
    FakeMessagingClient.reset()


@pytest.fixture
def ask(api_client, django_capture_on_commit_callbacks):
    def _ask(login):
        with django_capture_on_commit_callbacks(execute=True):
            return api_client.post(REQUEST, {"login": login}, format="json")

    return _ask


@pytest.fixture
def confirm(api_client):
    def _confirm(login, code, password=NEW_PASSWORD):
        body = {"login": login, "code": code, "password": password}
        return api_client.post(CONFIRM, body, format="json")

    return _confirm


def wrong(code):
    return f"{(int(code) + 1) % 1_000_000:06d}"


def assert_invalid(response):
    assert response.status_code == 400
    assert response.json()["code"] == "invalid_code"


pytestmark = pytest.mark.django_db


# --- Asking for a code -----------------------------------------------------


@pytest.mark.parametrize("factory", [ClientFactory, VendorUserFactory])
@pytest.mark.parametrize("login", ["0712345678", "+255 712 345 678", "ME@example.com"])
def test_code_goes_to_the_account_phone(ask, outbox, factory, login):
    factory(phone="+255712345678", email="me@example.com", preferred_language="sw")
    response = ask(login)
    assert response.status_code == 202
    (message,) = outbox
    assert message["phone"] == "255712345678"
    assert (message["template"], message["language"]) == ("auth_code", "sw")
    (code,) = message["params"]
    assert len(code) == 6
    assert code.isdigit()


def test_same_answer_for_every_login(ask, outbox):
    known = ask(ClientFactory().phone)
    outbox.clear()
    ineligible = [
        ClientFactory(is_active=False),
        AdminFactory(),
        ClientFactory(is_staff=True),
        VendorUserFactory(is_superuser=True),
        UserFactory(role=User.Role.ADMIN),
    ]
    for login in [*(u.phone for u in ineligible), "+255799999999", "a@b.example", "nonsense"]:
        response = ask(login)
        assert (response.status_code, response.json()) == (202, known.json())
    assert outbox == []


@pytest.mark.parametrize("body", [{}, {"login": ""}, {"login": None}, []])
def test_request_validation(api_client, body):
    assert api_client.post(REQUEST, body, format="json").status_code == 400


def test_code_is_stored_only_as_a_hash(ask, outbox, caplog):
    user = ClientFactory()
    Conversation.objects.create(wa_id=user.phone.lstrip("+"), user=user)
    with patch.object(
        tasks.send_password_code,
        "apply_async",
        wraps=tasks.send_password_code.apply_async,
    ) as queued:
        ask(user.phone)
    (code,) = outbox[0]["params"]
    assert queued.call_args.args == ((str(user.pk),),)
    assert queued.call_args.kwargs == {"expires": 600}
    assert code not in PasswordCode.objects.get().code_hash
    assert not ChatMessage.objects.exists()
    assert code not in caplog.text


def test_provider_problem_is_not_shown(ask):
    FakeMessagingClient.fail_with = MessagingError(transient=False)
    assert ask(ClientFactory().phone).status_code == 202


def test_transient_problem_is_retried_with_a_fresh_code():
    user = ClientFactory()
    FakeMessagingClient.fail_with = MessagingError(transient=True)
    with (
        patch.object(tasks.send_password_code, "retry", side_effect=RuntimeError) as retry,
        pytest.raises(RuntimeError),
    ):
        tasks.send_password_code(str(user.pk))
    assert retry.call_args.kwargs["countdown"] == 30


def test_task_without_template_or_user_sends_nothing(settings, outbox):
    user = ClientFactory()
    tasks.send_password_code("00000000-0000-0000-0000-000000000000")
    User.objects.filter(pk=user.pk).update(is_active=False)
    tasks.send_password_code(str(user.pk))
    User.objects.filter(pk=user.pk).update(is_active=True)
    settings.WHATSAPP_TEMPLATE_AUTH_CODE = ""
    tasks.send_password_code(str(user.pk))
    assert outbox == []


# --- Setting the password --------------------------------------------------


def test_whatsapp_account_can_be_claimed(ask, confirm, outbox, api_client):
    user = services.register_client(
        phone="0712345678",
        full_name="Asha",
        password=None,
        created_via=User.CreatedVia.WHATSAPP,
    )
    ask(user.phone)
    response = confirm("0712 345 678", outbox[0]["params"][0])
    assert response.status_code == 200
    assert set(response.json()) == {"access", "refresh"}
    body = {"login": user.phone, "password": NEW_PASSWORD}
    assert api_client.post(TOKEN, body).status_code == 200


def test_reset_signs_out_other_sessions(ask, confirm, outbox, api_client):
    user = ClientFactory()
    old = RefreshToken.for_user(user)
    ask(user.email)
    new = confirm(user.email, outbox[0]["params"][0]).json()

    def me(access):
        return api_client.get(ME, HTTP_AUTHORIZATION=f"Bearer {access}").status_code

    def refresh(token):
        return api_client.post(REFRESH, {"refresh": token})

    assert me(old.access_token) == 401
    assert refresh(str(old)).status_code == 401
    assert me(new["access"]) == 200
    renewed = refresh(new["refresh"])
    assert renewed.status_code == 200
    assert me(renewed.json()["access"]) == 200
    body = {"login": user.phone, "password": DEFAULT_PASSWORD}
    assert api_client.post(TOKEN, body).status_code == 401


def test_refresh_for_a_deleted_user(api_client):
    user = ClientFactory()
    token = str(RefreshToken.for_user(user))
    user.delete()
    assert api_client.post(REFRESH, {"refresh": token}).status_code == 401


def test_code_works_once(ask, confirm, outbox):
    user = ClientFactory()
    ask(user.phone)
    (code,) = outbox[0]["params"]
    assert confirm(user.phone, code).status_code == 200
    assert_invalid(confirm(user.phone, code))


def test_code_expires(ask, confirm, outbox):
    user = ClientFactory()
    with freeze_time() as clock:
        ask(user.phone)
        clock.tick(timedelta(minutes=10, seconds=1))
        assert_invalid(confirm(user.phone, outbox[0]["params"][0]))


def test_new_code_replaces_the_old_one(ask, confirm):
    user = ClientFactory()
    with patch("apps.accounts.services.secrets.randbelow", side_effect=[111, 222]):
        ask(user.phone)
        ask(user.phone)
    assert_invalid(confirm(user.phone, "000111"))
    assert confirm(user.phone, "000222").status_code == 200


def test_fresh_code_resets_attempts_and_use(ask, confirm, outbox):
    user = ClientFactory()
    ask(user.phone)
    for _ in range(5):
        assert_invalid(confirm(user.phone, wrong(outbox[0]["params"][0])))
    ask(user.phone)
    assert confirm(user.phone, outbox[1]["params"][0]).status_code == 200


def test_five_wrong_attempts_are_the_limit(ask, confirm, outbox):
    user = ClientFactory()
    ask(user.phone)
    (code,) = outbox[0]["params"]
    for _ in range(5):
        assert_invalid(confirm(user.phone, wrong(code)))
    assert_invalid(confirm(user.phone, code))
    user.refresh_from_db()
    assert user.check_password(DEFAULT_PASSWORD)


def test_code_of_another_user(ask, confirm):
    first, second = ClientFactory(), ClientFactory()
    with patch("apps.accounts.services.secrets.randbelow", side_effect=[111, 222]):
        ask(first.phone)
        ask(second.phone)
    assert_invalid(confirm(second.phone, "000111"))


def test_unknown_or_ineligible_login(confirm):
    admin = AdminFactory()
    services.issue_code(admin)
    blocked = ClientFactory(is_active=False)
    for login in ("+255799999999", "nonsense", admin.phone, blocked.phone, ClientFactory().phone):
        assert_invalid(confirm(login, "123456"))


def test_account_blocked_after_the_code_was_sent(ask, confirm, outbox):
    user = ClientFactory()
    ask(user.phone)
    User.objects.filter(pk=user.pk).update(is_active=False)
    assert_invalid(confirm(user.phone, outbox[0]["params"][0]))


def test_weak_password_keeps_the_code(ask, confirm, outbox):
    user = ClientFactory()
    ask(user.phone)
    (code,) = outbox[0]["params"]
    response = confirm(user.phone, code, "123")
    assert response.status_code == 400
    assert response.json()["errors"]["password"]
    assert confirm(user.phone, code).status_code == 200


@pytest.mark.parametrize("missing", ["login", "code", "password"])
def test_confirm_validation(api_client, missing):
    body = {"login": "0712345678", "code": "123456", "password": NEW_PASSWORD}
    del body[missing]
    response = api_client.post(CONFIRM, body, format="json")
    assert response.status_code == 400
    assert list(response.json()["errors"]) == [missing]


def test_changed_password_is_logged_without_personal_data(
    ask, confirm, outbox, caplog, django_capture_on_commit_callbacks
):
    caplog.set_level("INFO")
    user = ClientFactory()
    ask(user.phone)
    (code,) = outbox[0]["params"]
    with django_capture_on_commit_callbacks(execute=True):
        confirm(user.phone, code)
    events = [r.event for r in caplog.records if hasattr(r, "event")]
    assert "password.code_requested" in events
    assert "password.changed" in events
    logged = caplog.text + json.dumps([getattr(r, "data", {}) for r in caplog.records], default=str)
    for private in (user.phone, user.email, code, NEW_PASSWORD):
        assert private not in logged

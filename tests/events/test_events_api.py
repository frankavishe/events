import uuid
from datetime import timedelta

import pytest
from django.utils import timezone
from freezegun import freeze_time

from apps.events.models import Event
from tests.factories import (
    AdminFactory,
    ClientFactory,
    EventFactory,
    ServiceAreaFactory,
    VendorProfileFactory,
)

pytestmark = pytest.mark.django_db

URL = "/api/v1/events/"


def detail(event):
    return f"{URL}{event.pk}/"


def payload(**overrides):
    return {
        "event_type": "wedding",
        "title": "Harusi ya Asha",
        "starts_at": (timezone.now() + timedelta(days=20)).isoformat(),
        "venue": "Mlimani City",
        "guest_count": 200,
    } | overrides


@pytest.fixture
def owner():
    return ClientFactory()


class TestCreate:
    def test_success(self, auth_client, owner):
        area = ServiceAreaFactory()
        response = auth_client(owner).post(
            URL, payload(service_area=str(area.pk), client=str(ClientFactory().pk)), format="json"
        )
        assert response.status_code == 201, response.data
        event = Event.objects.get()
        assert event.client == owner
        assert event.service_area == area

    @pytest.mark.parametrize(
        ("override", "field"),
        [
            ({"event_type": "rave"}, "event_type"),
            ({"title": ""}, "title"),
            ({"venue": ""}, "venue"),
            ({"guest_count": 0}, "guest_count"),
            ({"starts_at": "not-a-date"}, "starts_at"),
            ({"starts_at": "2020-01-01T10:00:00+03:00"}, "starts_at"),
            ({"service_area": str(uuid.uuid4())}, "service_area"),
        ],
    )
    def test_validation(self, auth_client, owner, override, field):
        response = auth_client(owner).post(URL, payload(**override), format="json")
        assert response.status_code == 400
        assert field in response.json()["errors"]

    def test_permissions(self, api_client, auth_client):
        assert api_client.post(URL, payload(), format="json").status_code == 401
        for user in (VendorProfileFactory().user, AdminFactory()):
            assert auth_client(user).post(URL, payload(), format="json").status_code == 403


class TestOwnership:
    def test_list_own_only(self, auth_client, owner):
        mine = EventFactory(client=owner)
        EventFactory()
        body = auth_client(owner).get(URL).json()
        assert [e["id"] for e in body["results"]] == [str(mine.pk)]

    def test_others_event_is_404(self, auth_client, owner):
        event = EventFactory()
        client = auth_client(owner)
        assert client.get(detail(event)).status_code == 404
        assert client.patch(detail(event), {"title": "x"}, format="json").status_code == 404
        assert client.delete(detail(event)).status_code == 404
        assert Event.objects.filter(pk=event.pk).exists()


class TestUpdateDelete:
    def test_patch(self, auth_client, owner):
        event = EventFactory(client=owner)
        response = auth_client(owner).patch(detail(event), {"guest_count": 5}, format="json")
        assert response.status_code == 200
        event.refresh_from_db()
        assert event.guest_count == 5

    def test_cannot_move_into_past(self, auth_client, owner):
        event = EventFactory(client=owner)
        response = auth_client(owner).patch(
            detail(event), {"starts_at": "2020-01-01T10:00:00+03:00"}, format="json"
        )
        assert response.status_code == 400

    def test_past_event_can_be_edited_if_date_unchanged(self, auth_client, owner):
        event = EventFactory(client=owner)
        # Fresh token inside the frozen time, so it has not expired.
        with freeze_time(event.starts_at + timedelta(days=1)):
            response = auth_client(owner).patch(
                detail(event),
                {"notes": "Asante", "starts_at": event.starts_at.isoformat()},
                format="json",
            )
        assert response.status_code == 200, response.data

    def test_delete(self, auth_client, owner):
        event = EventFactory(client=owner)
        assert auth_client(owner).delete(detail(event)).status_code == 204
        assert not Event.objects.exists()

    def test_put_not_allowed(self, auth_client, owner):
        event = EventFactory(client=owner)
        assert auth_client(owner).put(detail(event), payload(), format="json").status_code == 405

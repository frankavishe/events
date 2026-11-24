import uuid

import pytest
from django.contrib.admin.sites import site
from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction

from apps.vendors.models import VendorProfile
from tests.factories import (
    AdminFactory,
    ClientFactory,
    ServiceAreaFactory,
    UserFactory,
    VendorProfileFactory,
    VendorUserFactory,
)

pytestmark = pytest.mark.django_db

User = get_user_model()

REGISTER_URL = "/api/v1/auth/register/vendor/"
PROFILE_URL = "/api/v1/vendor/profile/"
VENDORS_URL = "/api/v1/vendors/"
AREAS_URL = "/api/v1/service-areas/"


def action_url(vendor, action):
    return f"/api/v1/admin/vendors/{vendor.pk}/{action}/"


@pytest.fixture
def area():
    return ServiceAreaFactory()


@pytest.fixture
def payload(area):
    return {
        "full_name": "Juma Mpishi",
        "phone": "0712345678",
        "password": "Chakula-Bora-2026",
        "business_name": "Juma Catering",
        "description": "Pilau and more",
        "offers_food": True,
        "offers_drinks": False,
        "service_area_ids": [str(area.pk)],
        "min_notice_days": 3,
    }


class TestRegister:
    def test_creates_pending_vendor_with_tokens(self, api_client, payload, area):
        response = api_client.post(REGISTER_URL, payload, format="json")
        assert response.status_code == 201, response.data
        body = response.json()
        assert body["access"] and body["refresh"]
        assert body["user"]["role"] == "vendor"
        assert body["vendor"]["status"] == "pending"
        profile = VendorProfile.objects.get(user__phone="+255712345678")
        assert profile.contact_phone == "+255712345678"
        assert profile.min_notice_days == 3
        assert list(profile.service_areas.all()) == [area]

    def test_contact_phone_normalized(self, api_client, payload):
        response = api_client.post(
            REGISTER_URL, payload | {"contact_phone": "0655 111 222"}, format="json"
        )
        assert response.status_code == 201
        assert response.json()["vendor"]["contact_phone"] == "+255655111222"

    def test_status_cannot_be_set_by_caller(self, api_client, payload):
        api_client.post(REGISTER_URL, payload | {"status": "approved"}, format="json")
        assert VendorProfile.objects.get().status == "pending"

    @pytest.mark.parametrize(
        ("override", "field"),
        [
            ({"business_name": ""}, "business_name"),
            ({"offers_food": False}, "offers_food"),
            ({"service_area_ids": []}, "service_area_ids"),
            ({"service_area_ids": [str(uuid.uuid4())]}, "service_area_ids"),
            ({"min_notice_days": -1}, "min_notice_days"),
            ({"contact_phone": "123"}, "contact_phone"),
            ({"phone": "123"}, "phone"),
            ({"password": "short"}, "password"),
        ],
    )
    def test_validation(self, api_client, payload, override, field):
        response = api_client.post(REGISTER_URL, payload | override, format="json")
        assert response.status_code == 400
        assert field in response.json()["errors"]
        assert not User.objects.exists()

    def test_duplicate_phone(self, api_client, payload):
        UserFactory(phone="+255712345678")
        response = api_client.post(REGISTER_URL, payload, format="json")
        assert response.status_code == 400
        assert "phone" in response.json()["errors"]


class TestOwnProfile:
    def test_get_includes_payout_details(self, auth_client):
        vendor = VendorProfileFactory(payout_account_number="0712000000")
        response = auth_client(vendor.user).get(PROFILE_URL)
        assert response.status_code == 200
        assert response.json()["payout_account_number"] == "0712000000"

    def test_pending_vendor_can_edit_profile(self, auth_client, area):
        vendor = VendorProfileFactory(status="pending")
        response = auth_client(vendor.user).patch(
            PROFILE_URL,
            {
                "business_name": "New",
                "payout_method": "mobile_money",
                "service_area_ids": [str(area.pk)],
            },
            format="json",
        )
        assert response.status_code == 200, response.data
        vendor.refresh_from_db()
        assert vendor.business_name == "New"
        assert vendor.payout_method == "mobile_money"
        assert list(vendor.service_areas.all()) == [area]

    def test_status_is_read_only(self, auth_client):
        vendor = VendorProfileFactory(status="pending")
        auth_client(vendor.user).patch(PROFILE_URL, {"status": "approved"}, format="json")
        vendor.refresh_from_db()
        assert vendor.status == "pending"

    def test_must_offer_something_against_merged_state(self, auth_client):
        vendor = VendorProfileFactory(offers_food=True, offers_drinks=False)
        response = auth_client(vendor.user).patch(
            PROFILE_URL, {"offers_food": False}, format="json"
        )
        assert response.status_code == 400

    def test_permissions(self, api_client, auth_client):
        assert api_client.get(PROFILE_URL).status_code == 401
        assert auth_client(ClientFactory()).get(PROFILE_URL).status_code == 403
        # A vendor-role user whose profile does not exist (e.g. created in the admin).
        assert auth_client(VendorUserFactory()).get(PROFILE_URL).status_code == 404


class TestPublicVendors:
    def test_only_approved_and_no_private_fields(self, api_client):
        approved = VendorProfileFactory(payout_account_number="SECRET")
        hidden = [VendorProfileFactory(status=s) for s in ("pending", "rejected", "suspended")]
        body = api_client.get(VENDORS_URL).json()
        assert [v["id"] for v in body["results"]] == [str(approved.pk)]
        assert not any(key.startswith("payout") for key in body["results"][0])
        assert "user" not in body["results"][0]
        assert api_client.get(f"{VENDORS_URL}{approved.pk}/").status_code == 200
        for vendor in hidden:
            assert api_client.get(f"{VENDORS_URL}{vendor.pk}/").status_code == 404

    def test_deactivated_account_is_hidden(self, api_client):
        VendorProfileFactory(user__is_active=False)
        assert api_client.get(VENDORS_URL).json()["count"] == 0

    def test_filters(self, api_client, area):
        food = VendorProfileFactory(
            business_name="Pilau House", offers_drinks=False, service_areas=[area]
        )
        drinks = VendorProfileFactory(business_name="Soda Depot", offers_food=False)

        def ids(query):
            return [v["id"] for v in api_client.get(VENDORS_URL + query).json()["results"]]

        assert ids(f"?service_area={area.pk}") == [str(food.pk)]
        assert ids("?offers_drinks=true") == [str(drinks.pk)]
        assert ids("?offers_food=true") == [str(food.pk)]
        assert ids("?search=soda") == [str(drinks.pk)]

    def test_service_areas_public(self, api_client, area):
        response = api_client.get(AREAS_URL)
        assert response.status_code == 200
        assert response.json()["results"][0]["name"] == area.name


class TestModeration:
    @pytest.mark.parametrize(
        ("start", "action", "end"),
        [
            ("pending", "approve", "approved"),
            ("rejected", "approve", "approved"),
            ("suspended", "approve", "approved"),
            ("pending", "reject", "rejected"),
            ("approved", "suspend", "suspended"),
        ],
    )
    def test_allowed(self, auth_client, start, action, end):
        vendor = VendorProfileFactory(status=start)
        admin = AdminFactory()
        response = auth_client(admin).post(action_url(vendor, action))
        assert response.status_code == 200, response.data
        assert response.json()["status"] == end
        vendor.refresh_from_db()
        assert vendor.status == end
        if action == "approve":
            assert vendor.approved_by == admin
            assert vendor.approved_at is not None

    @pytest.mark.parametrize(
        ("start", "action"),
        [
            ("approved", "approve"),
            ("approved", "reject"),
            ("rejected", "reject"),
            ("suspended", "reject"),
            ("pending", "suspend"),
            ("rejected", "suspend"),
            ("suspended", "suspend"),
        ],
    )
    def test_forbidden_transitions(self, auth_client, start, action):
        vendor = VendorProfileFactory(status=start)
        response = auth_client(AdminFactory()).post(action_url(vendor, action))
        assert response.status_code == 409
        vendor.refresh_from_db()
        assert vendor.status == start

    @pytest.mark.parametrize("action", ["approve", "reject", "suspend"])
    def test_admin_only(self, api_client, auth_client, action):
        vendor = VendorProfileFactory(status="pending")
        url = action_url(vendor, action)
        assert api_client.post(url).status_code == 401
        assert auth_client(ClientFactory()).post(url).status_code == 403
        assert auth_client(vendor.user).post(url).status_code == 403

    def test_unknown_vendor(self, auth_client):
        url = f"/api/v1/admin/vendors/{uuid.uuid4()}/approve/"
        assert auth_client(AdminFactory()).post(url).status_code == 404


class TestModelAndAdmin:
    def test_db_rejects_vendor_offering_nothing(self):
        with pytest.raises(IntegrityError), transaction.atomic():
            VendorProfileFactory(offers_food=False, offers_drinks=False)

    def test_admin_approve_action_uses_service(self, client):
        admin = AdminFactory(is_superuser=True)
        vendor = VendorProfileFactory(status="pending")
        already = VendorProfileFactory(status="approved")
        client.force_login(admin)
        response = client.post(
            "/admin/vendors/vendorprofile/",
            {
                "action": "approve_vendors",
                "_selected_action": [str(vendor.pk), str(already.pk)],
            },
        )
        assert response.status_code == 302
        vendor.refresh_from_db()
        assert vendor.status == "approved"
        assert vendor.approved_by == admin

    def test_status_read_only_in_admin(self):
        assert "status" in site.get_model_admin(VendorProfile).readonly_fields

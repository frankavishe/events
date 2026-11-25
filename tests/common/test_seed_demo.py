from io import StringIO

import pytest
from django.core.management import CommandError, call_command

from apps.accounts.models import User
from apps.catalog.models import Item, Package
from apps.catalog.services import public_items, public_packages
from apps.vendors.models import ServiceArea, VendorProfile
from apps.vendors.services import public_vendors

pytestmark = pytest.mark.django_db

PASSWORD = "Karibu-Demo-2026"
MODELS = (User, VendorProfile, ServiceArea, Item, Package)


def seed(**options):
    out = StringIO()
    call_command("seed_demo", stdout=out, **options)
    return out.getvalue()


def counts():
    return [model.objects.count() for model in MODELS]


def test_refuses_outside_debug(settings):
    settings.DEBUG = False
    before = counts()
    with pytest.raises(CommandError):
        seed(password=PASSWORD)
    assert counts() == before


def test_seeds_a_public_catalog_once(settings):
    settings.DEBUG = True
    seed(password=PASSWORD)
    assert public_vendors().count() >= 2
    items = public_items()
    assert {"food", "drink"} == set(items.values_list("kind", flat=True))
    assert items.filter(is_alcoholic=True).exists()
    assert public_packages().exists()
    for vendor in public_vendors():
        assert vendor.service_areas.exists()
        assert vendor.approved_by is not None
    first = counts()
    seed(password="Another-Pass-2026")
    assert counts() == first


def test_demo_users_can_log_in(settings, api_client):
    settings.DEBUG = True
    seed(password=PASSWORD)
    roles = set()
    for user in User.objects.filter(email__endswith="@demo.example"):
        if user.role == "admin":
            assert not user.has_usable_password()
            continue
        body = {"login": user.email, "password": PASSWORD}
        assert api_client.post("/api/v1/auth/token/", body).status_code == 200
        roles.add(user.role)
    assert roles == {"client", "vendor"}


def test_random_password_is_printed_once(settings, api_client):
    settings.DEBUG = True
    output = seed()
    password = output.split("Password for new demo users: ")[1].split()[0]
    user = User.objects.get(email="client@demo.example")
    assert user.check_password(password)
    assert "Password" not in seed()

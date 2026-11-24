from types import SimpleNamespace

import pytest
from django.contrib.auth.models import AnonymousUser

from apps.common.permissions import IsAdmin, IsApprovedVendor, IsClient, IsVendor
from tests.factories import (
    AdminFactory,
    UserFactory,
    VendorProfileFactory,
    VendorUserFactory,
)

pytestmark = pytest.mark.django_db


def check(permission_cls, user):
    request = SimpleNamespace(user=user)
    return permission_cls().has_permission(request, view=None)


class TestRolePermissions:
    @pytest.mark.parametrize(
        ("permission", "client", "vendor", "admin"),
        [
            (IsClient, True, False, False),
            (IsVendor, False, True, False),
            (IsAdmin, False, False, True),
        ],
    )
    def test_role_matrix(self, permission, client, vendor, admin):
        assert check(permission, UserFactory()) is client
        assert check(permission, VendorUserFactory()) is vendor
        assert check(permission, AdminFactory()) is admin

    @pytest.mark.parametrize("permission", [IsClient, IsVendor, IsApprovedVendor, IsAdmin])
    def test_anonymous_denied(self, permission):
        assert check(permission, AnonymousUser()) is False

    @pytest.mark.parametrize("permission", [IsClient, IsVendor, IsAdmin])
    def test_inactive_denied(self, permission):
        for factory in (UserFactory, VendorUserFactory, AdminFactory):
            assert check(permission, factory(is_active=False)) is False

    def test_superuser_without_admin_role_is_admin(self):
        user = UserFactory(is_superuser=True, is_staff=True)
        assert check(IsAdmin, user) is True


class TestIsApprovedVendor:
    def test_non_vendor_denied(self):
        assert check(IsApprovedVendor, UserFactory()) is False

    def test_vendor_without_profile_denied(self):
        assert check(IsApprovedVendor, VendorUserFactory()) is False

    def test_uses_vendor_profile_status(self):
        for status in ("pending", "suspended", "rejected"):
            assert check(IsApprovedVendor, VendorProfileFactory(status=status).user) is False
        assert check(IsApprovedVendor, VendorProfileFactory(status="approved").user) is True

    def test_denial_message_is_explanatory(self):
        assert "approved" in IsApprovedVendor.message.lower()

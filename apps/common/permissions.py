"""Role-based DRF permissions. Object scoping (own records only) is done in querysets."""

from rest_framework.permissions import BasePermission

ROLE_CLIENT = "client"
ROLE_VENDOR = "vendor"
ROLE_ADMIN = "admin"
VENDOR_APPROVED = "approved"


def _active(user):
    return bool(user and user.is_authenticated and user.is_active)


def is_admin(user) -> bool:
    return _active(user) and (user.role == ROLE_ADMIN or user.is_superuser)


class IsClient(BasePermission):
    message = "Only client accounts can perform this action."

    def has_permission(self, request, view):
        return _active(request.user) and request.user.role == ROLE_CLIENT


class IsVendor(BasePermission):
    message = "Only vendor accounts can perform this action."

    def has_permission(self, request, view):
        return _active(request.user) and request.user.role == ROLE_VENDOR


class IsApprovedVendor(BasePermission):
    message = "Your vendor account must be approved before you can do this."

    def has_permission(self, request, view):
        user = request.user
        if not (_active(user) and user.role == ROLE_VENDOR):
            return False
        profile = getattr(user, "vendor_profile", None)
        return getattr(profile, "status", None) == VENDOR_APPROVED


class IsAdmin(BasePermission):
    message = "Only platform administrators can perform this action."

    def has_permission(self, request, view):
        return is_admin(request.user)

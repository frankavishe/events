"""Vendor business logic: registration, moderation and public visibility."""

from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone

from apps.accounts.models import User
from apps.common.exceptions import Conflict

from .models import VendorProfile

Status = VendorProfile.Status

# {target status: statuses it may be reached from}
ALLOWED_FROM = {
    Status.APPROVED: {Status.PENDING, Status.REJECTED, Status.SUSPENDED},
    Status.REJECTED: {Status.PENDING},
    Status.SUSPENDED: {Status.APPROVED},
}


def public_vendors():
    """Vendors clients may see. The single definition of vendor visibility."""
    return VendorProfile.objects.filter(status=Status.APPROVED, user__is_active=True)


@transaction.atomic
def register_vendor(
    *,
    phone: str,
    full_name: str,
    password: str,
    business_name: str,
    service_areas,
    offers_food: bool = False,
    offers_drinks: bool = False,
    description: str = "",
    contact_phone: str = "",
    min_notice_days: int = 2,
    email: str | None = None,
    preferred_language: str = User.Language.EN,
) -> VendorProfile:
    user = User.objects.create_user(
        phone=phone,
        full_name=full_name,
        password=password,
        email=email,
        preferred_language=preferred_language,
        role=User.Role.VENDOR,
        created_via=User.CreatedVia.API,
    )
    vendor = VendorProfile.objects.create(
        user=user,
        business_name=business_name,
        description=description,
        contact_phone=contact_phone or user.phone,
        offers_food=offers_food,
        offers_drinks=offers_drinks,
        min_notice_days=min_notice_days,
    )
    vendor.service_areas.set(service_areas)
    return vendor


@transaction.atomic
def _set_status(vendor_id, target, *, actor=None) -> VendorProfile:
    vendor = get_object_or_404(VendorProfile.objects.select_for_update(), pk=vendor_id)
    if vendor.status not in ALLOWED_FROM[target]:
        raise Conflict(f"A vendor that is {vendor.status} cannot become {target.value}.")
    vendor.status = target
    if target == Status.APPROVED:
        vendor.approved_by = actor
        vendor.approved_at = timezone.now()
    vendor.save(update_fields=["status", "approved_by", "approved_at", "updated_at"])
    return vendor


def approve(vendor_id, actor) -> VendorProfile:
    return _set_status(vendor_id, Status.APPROVED, actor=actor)


def reject(vendor_id) -> VendorProfile:
    return _set_status(vendor_id, Status.REJECTED)


def suspend(vendor_id) -> VendorProfile:
    return _set_status(vendor_id, Status.SUSPENDED)

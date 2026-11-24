from datetime import timedelta
from decimal import Decimal

import factory
from django.contrib.auth import get_user_model
from django.utils import timezone

from apps.catalog.models import Category, Item, Package, PackageItem
from apps.events.models import Event
from apps.vendors.models import ServiceArea, VendorProfile

User = get_user_model()

DEFAULT_PASSWORD = "Chakula-Bora-2026"


class UserFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = User
        skip_postgeneration_save = True

    phone = factory.Sequence(lambda n: f"+2557{n:08d}")
    full_name = factory.Faker("name")
    email = factory.Sequence(lambda n: f"user{n}@example.com")
    role = User.Role.CLIENT
    preferred_language = "en"
    is_active = True

    @factory.post_generation
    def password(self, create, extracted, **kwargs):
        self.set_password(extracted or DEFAULT_PASSWORD)
        if create:
            self.save(update_fields=["password"])


class ClientFactory(UserFactory):
    role = User.Role.CLIENT


class VendorUserFactory(UserFactory):
    role = User.Role.VENDOR


class AdminFactory(UserFactory):
    role = User.Role.ADMIN
    is_staff = True


class ServiceAreaFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = ServiceArea

    name = factory.Sequence(lambda n: f"Area {n}")


class VendorProfileFactory(factory.django.DjangoModelFactory):
    """An approved vendor unless `status` is given."""

    class Meta:
        model = VendorProfile
        skip_postgeneration_save = True

    user = factory.SubFactory(VendorUserFactory)
    business_name = factory.Sequence(lambda n: f"Vendor {n}")
    contact_phone = factory.SelfAttribute("user.phone")
    status = VendorProfile.Status.APPROVED
    offers_food = True
    offers_drinks = True

    @factory.post_generation
    def service_areas(self, create, extracted, **kwargs):
        if create and extracted:
            self.service_areas.set(extracted)


class CategoryFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Category

    name_en = factory.Sequence(lambda n: f"Category {n}")
    name_sw = factory.Sequence(lambda n: f"Aina {n}")
    slug = factory.Sequence(lambda n: f"category-{n}")
    kind = "food"


class ItemFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Item

    vendor = factory.SubFactory(VendorProfileFactory)
    kind = "food"
    category = factory.SubFactory(CategoryFactory, kind=factory.SelfAttribute("..kind"))
    name = factory.Sequence(lambda n: f"Item {n}")
    unit = Item.Unit.PLATE
    unit_price = Decimal("15000.00")


class PackageFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Package
        skip_postgeneration_save = True

    vendor = factory.SubFactory(VendorProfileFactory)
    name = factory.Sequence(lambda n: f"Package {n}")
    pricing = Package.Pricing.PER_GUEST
    price = Decimal("25000.00")

    @factory.post_generation
    def items(self, create, extracted, **kwargs):
        for item in extracted or []:
            PackageItem.objects.create(package=self, item=item)


class EventFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Event

    client = factory.SubFactory(ClientFactory)
    event_type = Event.Type.WEDDING
    title = factory.Sequence(lambda n: f"Event {n}")
    starts_at = factory.LazyFunction(lambda: timezone.now() + timedelta(days=30))
    venue = "Mlimani City Hall"
    guest_count = 100

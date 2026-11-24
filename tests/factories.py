from datetime import timedelta
from decimal import Decimal

import factory
from django.contrib.auth import get_user_model
from django.utils import timezone

from apps.catalog.models import Category, Item, Package, PackageItem
from apps.events.models import Event
from apps.orders.models import Order, OrderLine
from apps.payments.models import Payment
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


class OrderFactory(factory.django.DjangoModelFactory):
    """A pending order. Use `status=` to start elsewhere in the lifecycle."""

    class Meta:
        model = Order

    reference = factory.Sequence(lambda n: f"EVT-260101-{n:04d}")
    client = factory.SubFactory(ClientFactory)
    event = factory.SubFactory(EventFactory, client=factory.SelfAttribute("..client"))
    vendor = factory.SubFactory(VendorProfileFactory)
    status = Order.Status.PENDING
    subtotal = Decimal("150000.00")
    total = factory.SelfAttribute("subtotal")
    expires_at = factory.LazyFunction(lambda: timezone.now() + timedelta(hours=24))


class OrderLineFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = OrderLine

    order = factory.SubFactory(OrderFactory)
    item = factory.SubFactory(ItemFactory, vendor=factory.SelfAttribute("..order.vendor"))
    name_snapshot = factory.SelfAttribute("item.name")
    unit_snapshot = factory.SelfAttribute("item.unit")
    unit_price_snapshot = factory.SelfAttribute("item.unit_price")
    quantity = 10
    line_total = factory.LazyAttribute(lambda o: o.unit_price_snapshot * o.quantity)


class PaymentFactory(factory.django.DjangoModelFactory):
    """A pending M-Pesa payment for a confirmed order."""

    class Meta:
        model = Payment

    order = factory.SubFactory(OrderFactory, status=Order.Status.CONFIRMED)
    method = Payment.Method.ONLINE
    provider = Payment.Provider.MPESA
    payer_phone = "+255712345678"
    amount = factory.SelfAttribute("order.total")

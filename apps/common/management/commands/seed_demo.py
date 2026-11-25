"""Demo data for local development."""

import secrets
from decimal import Decimal

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.accounts.models import User
from apps.accounts.services import register_client
from apps.catalog.models import Category, Item, Package
from apps.catalog.services import save_item, save_package
from apps.vendors.models import ServiceArea
from apps.vendors.services import approve, register_vendor

AREAS = ("Dar es Salaam - Kinondoni", "Dar es Salaam - Ilala", "Arusha", "Mwanza")
ADMIN = ("admin@demo.example", "+255700000100")
CLIENT = ("client@demo.example", "+255700000101")

# (category, name, description, unit, price, minimum quantity, alcoholic)
VENDORS = (
    {
        "email": "mama.asha@demo.example",
        "phone": "+255700000102",
        "full_name": "Asha Juma",
        "business_name": "Mama Asha Catering",
        "description": "Vyakula vya sherehe / Food for celebrations",
        "areas": AREAS[:2],
        "items": (
            ("main-dishes", "Pilau ya nyama", "Spiced rice with beef", "plate", 12000, 20, False),
            ("main-dishes", "Wali na kuku", "Rice with chicken", "plate", 10000, 20, False),
            ("snacks", "Sambusa", "Beef samosa", "piece", 1000, 50, False),
            ("desserts", "Matunda", "Fresh fruit platter", "tray", 35000, 1, False),
            ("juice", "Juisi ya embe", "Fresh mango juice", "litre", 6000, 5, False),
        ),
        "package": (
            "Kifurushi cha Harusi",
            "Wedding package: pilau, snacks and juice",
            "per_guest",
            25000,
            50,
            ("Pilau ya nyama", "Sambusa", "Juisi ya embe"),
        ),
    },
    {
        "email": "kili.drinks@demo.example",
        "phone": "+255700000103",
        "full_name": "Neema Mushi",
        "business_name": "Kili Drinks",
        "description": "Vinywaji vya aina zote / All kinds of drinks",
        "areas": AREAS,
        "items": (
            ("soft-drinks", "Soda (kreti)", "Crate of 24 sodas", "crate", 18000, 1, False),
            ("water", "Maji ya kunywa", "Drinking water, 500 ml", "bottle", 700, 24, False),
            ("beer", "Bia (kreti)", "Crate of 24 local lagers", "crate", 60000, 1, True),
            ("wine", "Mvinyo mwekundu", "Red wine, 750 ml", "bottle", 28000, 1, True),
        ),
        "package": (
            "Vinywaji baridi",
            "Soft drinks for a party",
            "flat",
            150000,
            1,
            ("Soda (kreti)", "Maji ya kunywa"),
        ),
    },
)


class Command(BaseCommand):
    help = "Create demo areas, vendors, items, packages and users. Safe to repeat. DEBUG only."

    def add_arguments(self, parser):
        parser.add_argument("--password", help="For new demo users; random if not given.")

    @transaction.atomic
    def handle(self, *args, password=None, **options):
        if not settings.DEBUG:
            raise CommandError("seed_demo only runs with DEBUG on.")
        generated = None if password else secrets.token_urlsafe(12)
        password = password or generated
        areas = {name: ServiceArea.objects.get_or_create(name=name)[0] for name in AREAS}

        created = self._users(password)
        for data in VENDORS:
            created += self._vendor(data, areas, password)

        if generated and created:
            self.stdout.write(f"Password for new demo users: {generated}")
        self.stdout.write(f"Demo data ready ({created} new users).")

    def _users(self, password) -> int:
        created = 0
        email, phone = ADMIN
        if not _exists(email):
            # Only to approve the demo vendors: it cannot log in.
            User.objects.create_user(
                phone=phone,
                full_name="Demo Admin",
                password=None,
                email=email,
                role=User.Role.ADMIN,
            )
            created += 1
        email, phone = CLIENT
        if not _exists(email):
            register_client(full_name="Demo Client", phone=phone, email=email, password=password)
            created += 1
        return created

    def _vendor(self, data, areas, password) -> int:
        if _exists(data["email"]):
            return 0
        vendor = register_vendor(
            phone=data["phone"],
            full_name=data["full_name"],
            password=password,
            email=data["email"],
            preferred_language=User.Language.SW,
            business_name=data["business_name"],
            description=data["description"],
            service_areas=[areas[name] for name in data["areas"]],
            offers_food=any(i[0] in ("main-dishes", "snacks", "desserts") for i in data["items"]),
            offers_drinks=True,
        )
        approve(vendor.pk, User.objects.get(email=ADMIN[0]))

        items = {}
        for slug, name, description, unit, price, minimum, alcoholic in data["items"]:
            category = Category.objects.get(slug=slug)
            items[name] = save_item(
                Item(vendor=vendor),
                category=category,
                kind=category.kind,
                name=name,
                description=description,
                unit=unit,
                unit_price=Decimal(price),
                min_quantity=minimum,
                is_alcoholic=alcoholic,
            )
        name, description, pricing, price, guests, contents = data["package"]
        save_package(
            Package(vendor=vendor),
            items=[{"item": items[content]} for content in contents],
            name=name,
            description=description,
            pricing=pricing,
            price=Decimal(price),
            min_guests=guests,
        )
        return 1


def _exists(email) -> bool:
    return User.objects.filter(email=email).exists()

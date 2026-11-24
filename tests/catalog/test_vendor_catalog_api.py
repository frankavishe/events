import uuid
from decimal import Decimal

import pytest
from django.db import IntegrityError, transaction

from apps.catalog.models import Category, Item, Package
from tests.factories import (
    CategoryFactory,
    ClientFactory,
    ItemFactory,
    PackageFactory,
    VendorProfileFactory,
    VendorUserFactory,
)

pytestmark = pytest.mark.django_db

ITEMS_URL = "/api/v1/vendor/items/"
PACKAGES_URL = "/api/v1/vendor/packages/"


@pytest.fixture
def vendor():
    return VendorProfileFactory()


@pytest.fixture
def food():
    return CategoryFactory(kind="food")


@pytest.fixture
def drink():
    return CategoryFactory(kind="drink")


def item_payload(category, /, **overrides):
    return {
        "category": str(category.pk),
        "name": "Pilau",
        "kind": category.kind,
        "unit": "plate",
        "unit_price": "15000.00",
        "min_quantity": 10,
    } | overrides


class TestItems:
    def test_create(self, auth_client, vendor, food):
        response = auth_client(vendor.user).post(ITEMS_URL, item_payload(food), format="json")
        assert response.status_code == 201, response.data
        assert response.json()["unit_price"] == "15000.00"
        item = Item.objects.get()
        assert item.vendor == vendor
        assert item.is_available is True
        assert item.is_alcoholic is False

    def test_vendor_cannot_be_spoofed(self, auth_client, vendor, food):
        other = VendorProfileFactory()
        auth_client(vendor.user).post(
            ITEMS_URL, item_payload(food, vendor=str(other.pk)), format="json"
        )
        assert Item.objects.get().vendor == vendor

    def test_alcoholic_drink_allowed(self, auth_client, vendor, drink):
        response = auth_client(vendor.user).post(
            ITEMS_URL, item_payload(drink, is_alcoholic=True, unit="crate"), format="json"
        )
        assert response.status_code == 201
        assert response.json()["is_alcoholic"] is True

    def test_drink_must_be_classified(self, auth_client, vendor, drink):
        response = auth_client(vendor.user).post(ITEMS_URL, item_payload(drink), format="json")
        assert response.status_code == 400
        assert "is_alcoholic" in response.json()["errors"]

    @pytest.mark.parametrize(
        ("override", "field"),
        [
            ({"is_alcoholic": True}, "is_alcoholic"),
            ({"unit_price": "0"}, "unit_price"),
            ({"unit_price": "-5"}, "unit_price"),
            ({"unit_price": "10.005"}, "unit_price"),
            ({"min_quantity": 0}, "min_quantity"),
            ({"unit": "truck"}, "unit"),
            ({"name": ""}, "name"),
            ({"category": str(uuid.uuid4())}, "category"),
        ],
    )
    def test_validation(self, auth_client, vendor, food, override, field):
        response = auth_client(vendor.user).post(
            ITEMS_URL, item_payload(food, **override), format="json"
        )
        assert response.status_code == 400
        assert field in response.json()["errors"]

    def test_category_kind_must_match(self, auth_client, vendor, drink):
        response = auth_client(vendor.user).post(
            ITEMS_URL, item_payload(drink, kind="food"), format="json"
        )
        assert response.status_code == 400
        assert "category" in response.json()["errors"]

    def test_patch_and_delete(self, auth_client, vendor):
        item = ItemFactory(vendor=vendor)
        client = auth_client(vendor.user)
        url = f"{ITEMS_URL}{item.pk}/"
        assert client.patch(url, {"is_available": False}, format="json").status_code == 200
        item.refresh_from_db()
        assert item.is_available is False
        assert client.delete(url).status_code == 204
        assert not Item.objects.exists()

    def test_put_not_allowed(self, auth_client, vendor, food):
        item = ItemFactory(vendor=vendor)
        response = auth_client(vendor.user).put(
            f"{ITEMS_URL}{item.pk}/", item_payload(food), format="json"
        )
        assert response.status_code == 405

    def test_patch_validates_merged_state(self, auth_client, vendor):
        item = ItemFactory(vendor=vendor, kind="food")
        client = auth_client(vendor.user)
        url = f"{ITEMS_URL}{item.pk}/"
        assert client.patch(url, {"is_alcoholic": True}, format="json").status_code == 400
        assert client.patch(url, {"kind": "drink"}, format="json").status_code == 400

    def test_list_is_own_including_unavailable(self, auth_client, vendor):
        mine = ItemFactory(vendor=vendor, is_available=False)
        ItemFactory()
        body = auth_client(vendor.user).get(ITEMS_URL).json()
        assert [i["id"] for i in body["results"]] == [str(mine.pk)]

    def test_other_vendors_item_is_404(self, auth_client, vendor):
        url = f"{ITEMS_URL}{ItemFactory().pk}/"
        client = auth_client(vendor.user)
        assert client.get(url).status_code == 404
        assert client.patch(url, {"name": "x"}, format="json").status_code == 404
        assert client.delete(url).status_code == 404
        assert Item.objects.count() == 1

    def test_item_used_in_package_cannot_be_deleted(self, auth_client, vendor):
        item = ItemFactory(vendor=vendor)
        PackageFactory(vendor=vendor, items=[item])
        response = auth_client(vendor.user).delete(f"{ITEMS_URL}{item.pk}/")
        assert response.status_code == 409
        assert response.json()["code"] == "item_in_use"
        assert Item.objects.filter(pk=item.pk).exists()


@pytest.mark.parametrize("url", [ITEMS_URL, PACKAGES_URL])
class TestPermissions:
    def test_anonymous_and_client(self, api_client, auth_client, url):
        assert api_client.get(url).status_code == 401
        client = auth_client(ClientFactory())
        assert client.get(url).status_code == 403
        assert client.post(url, {}, format="json").status_code == 403

    @pytest.mark.parametrize("status", ["pending", "rejected", "suspended"])
    def test_unapproved_vendor_reads_but_cannot_write(self, auth_client, url, status):
        vendor = VendorProfileFactory(status=status)
        client = auth_client(vendor.user)
        assert client.get(url).status_code == 200
        assert client.post(url, {}, format="json").status_code == 403
        assert client.patch(f"{url}{uuid.uuid4()}/", {}, format="json").status_code == 403
        assert client.delete(f"{url}{uuid.uuid4()}/").status_code == 403

    def test_vendor_user_without_profile(self, auth_client, url):
        client = auth_client(VendorUserFactory())
        assert client.get(url).json()["count"] == 0
        assert client.post(url, {}, format="json").status_code == 403


class TestPackages:
    def payload(self, *items, **overrides):
        return {
            "name": "Harusi",
            "pricing": "per_guest",
            "price": "25000.00",
            "min_guests": 50,
            "items": [{"item_id": str(i.pk), "quantity_note": "1 per guest"} for i in items],
        } | overrides

    def test_create(self, auth_client, vendor):
        food = ItemFactory(vendor=vendor)
        beer = ItemFactory(vendor=vendor, kind="drink", is_alcoholic=True)
        response = auth_client(vendor.user).post(
            PACKAGES_URL, self.payload(food, beer), format="json"
        )
        assert response.status_code == 201, response.data
        body = response.json()
        assert body["contains_alcohol"] is True
        assert {i["item"]["id"] for i in body["items"]} == {str(food.pk), str(beer.pk)}
        assert body["items"][0]["quantity_note"] == "1 per guest"
        assert Package.objects.get().vendor == vendor

    def test_rejects_other_vendors_item(self, auth_client, vendor):
        response = auth_client(vendor.user).post(
            PACKAGES_URL, self.payload(ItemFactory()), format="json"
        )
        assert response.status_code == 400
        assert "items" in response.json()["errors"]
        assert not Package.objects.exists()

    def test_rejects_duplicate_items(self, auth_client, vendor):
        item = ItemFactory(vendor=vendor)
        response = auth_client(vendor.user).post(
            PACKAGES_URL, self.payload(item, item), format="json"
        )
        assert response.status_code == 400
        assert "items" in response.json()["errors"]

    @pytest.mark.parametrize(
        ("override", "field"),
        [
            ({"items": []}, "items"),
            ({"items": [{"item_id": "nope"}]}, "items"),
            ({"price": "0"}, "price"),
            ({"min_guests": 0}, "min_guests"),
            ({"pricing": "hourly"}, "pricing"),
        ],
    )
    def test_validation(self, auth_client, vendor, override, field):
        payload = self.payload(ItemFactory(vendor=vendor), **override)
        response = auth_client(vendor.user).post(PACKAGES_URL, payload, format="json")
        assert response.status_code == 400
        assert field in response.json()["errors"]

    def test_patch_without_items_keeps_them(self, auth_client, vendor):
        package = PackageFactory(vendor=vendor, items=[ItemFactory(vendor=vendor)])
        response = auth_client(vendor.user).patch(
            f"{PACKAGES_URL}{package.pk}/", {"price": "30000.00"}, format="json"
        )
        assert response.status_code == 200, response.data
        package.refresh_from_db()
        assert package.price == Decimal("30000.00")
        assert package.package_items.count() == 1

    def test_patch_replaces_items(self, auth_client, vendor):
        old, new = ItemFactory.create_batch(2, vendor=vendor)
        package = PackageFactory(vendor=vendor, items=[old])
        response = auth_client(vendor.user).patch(
            f"{PACKAGES_URL}{package.pk}/", {"items": [{"item_id": str(new.pk)}]}, format="json"
        )
        assert response.status_code == 200, response.data
        assert [i["item"]["id"] for i in response.json()["items"]] == [str(new.pk)]

    def test_rejected_patch_changes_nothing(self, auth_client, vendor):
        package = PackageFactory(vendor=vendor, items=[ItemFactory(vendor=vendor)], name="Old")
        response = auth_client(vendor.user).patch(
            f"{PACKAGES_URL}{package.pk}/",
            {"name": "New", "items": [{"item_id": str(ItemFactory().pk)}]},
            format="json",
        )
        assert response.status_code == 400
        package.refresh_from_db()
        assert package.name == "Old"
        assert package.package_items.count() == 1

    def test_delete_keeps_items(self, auth_client, vendor):
        package = PackageFactory(vendor=vendor, items=[ItemFactory(vendor=vendor)])
        response = auth_client(vendor.user).delete(f"{PACKAGES_URL}{package.pk}/")
        assert response.status_code == 204
        assert Item.objects.count() == 1

    def test_other_vendors_package_is_404(self, auth_client, vendor):
        url = f"{PACKAGES_URL}{PackageFactory().pk}/"
        client = auth_client(vendor.user)
        assert client.get(url).status_code == 404
        assert client.patch(url, {"name": "x"}, format="json").status_code == 404
        assert client.delete(url).status_code == 404


class TestConstraintsAndSeed:
    @pytest.mark.parametrize(
        "bad",
        [
            {"kind": "food", "is_alcoholic": True},
            {"unit_price": Decimal("0")},
            {"min_quantity": 0},
        ],
    )
    def test_item_db_constraints(self, bad):
        with pytest.raises(IntegrityError), transaction.atomic():
            ItemFactory(**bad)

    @pytest.mark.parametrize("bad", [{"price": Decimal("0")}, {"min_guests": 0}])
    def test_package_db_constraints(self, bad):
        with pytest.raises(IntegrityError), transaction.atomic():
            PackageFactory(**bad)

    def test_categories_seeded_bilingually(self):
        slugs = set(Category.objects.values_list("slug", flat=True))
        assert {"main-dishes", "soft-drinks", "beer", "wine", "spirits"} <= slugs
        assert not Category.objects.filter(name_sw="").exists()
        assert Category.objects.get(slug="beer").kind == "drink"

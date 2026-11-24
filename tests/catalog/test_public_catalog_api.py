from decimal import Decimal

import pytest

from apps.catalog import services
from tests.factories import (
    CategoryFactory,
    ItemFactory,
    PackageFactory,
    ServiceAreaFactory,
    VendorProfileFactory,
)

pytestmark = pytest.mark.django_db

ITEMS_URL = "/api/v1/items/"
PACKAGES_URL = "/api/v1/packages/"
CATEGORIES_URL = "/api/v1/categories/"


@pytest.fixture
def ids(api_client):
    def _ids(url):
        response = api_client.get(url)
        assert response.status_code == 200, response.data
        return [row["id"] for row in response.json()["results"]]

    return _ids


def pk(*objects):
    return [str(o.pk) for o in objects]


@pytest.mark.parametrize(
    ("url", "factory"), [(ITEMS_URL, ItemFactory), (PACKAGES_URL, PackageFactory)]
)
class TestVisibility:
    def test_only_available_from_approved_vendors(self, api_client, ids, url, factory):
        visible = factory()
        hidden = [factory(is_available=False), factory(vendor__user__is_active=False)]
        hidden += [factory(vendor__status=s) for s in ("pending", "rejected", "suspended")]
        assert ids(url) == pk(visible)
        assert api_client.get(f"{url}{visible.pk}/").status_code == 200
        for obj in hidden:
            assert api_client.get(f"{url}{obj.pk}/").status_code == 404

    def test_read_only(self, api_client, auth_client, url, factory):
        assert api_client.post(url, {}, format="json").status_code == 405
        obj = factory()
        client = auth_client(obj.vendor.user)
        assert client.post(url, {}, format="json").status_code == 405
        assert client.delete(f"{url}{obj.pk}/").status_code == 405

    def test_vendor_summary_has_no_private_fields(self, api_client, url, factory):
        factory()
        vendor = api_client.get(url).json()["results"][0]["vendor"]
        assert set(vendor) == {"id", "business_name"}

    def test_list_query_count_is_constant(
        self, api_client, django_assert_max_num_queries, url, factory
    ):
        factory.create_batch(5)
        with django_assert_max_num_queries(4):
            api_client.get(url)

    @pytest.mark.parametrize(
        "query", ["vendor=nope", "min_price=abc", "kind=metal", "category=unknown-slug"]
    )
    def test_invalid_filter_is_400(self, api_client, url, factory, query):
        assert api_client.get(f"{url}?{query}").status_code == 400


class TestItemFilters:
    def test_kind_and_alcohol(self, ids):
        food = ItemFactory()
        soda = ItemFactory(kind="drink")
        beer = ItemFactory(kind="drink", is_alcoholic=True)
        assert ids(f"{ITEMS_URL}?kind=food") == pk(food)
        assert ids(f"{ITEMS_URL}?kind=drink&is_alcoholic=false") == pk(soda)
        assert ids(f"{ITEMS_URL}?is_alcoholic=true") == pk(beer)

    def test_category_vendor_area(self, ids):
        areas = ServiceAreaFactory.create_batch(2)
        target = ItemFactory(category=CategoryFactory(slug="nyama"), vendor__service_areas=areas)
        ItemFactory()
        assert ids(f"{ITEMS_URL}?category=nyama") == pk(target)
        assert ids(f"{ITEMS_URL}?vendor={target.vendor.pk}") == pk(target)
        assert ids(f"{ITEMS_URL}?service_area={areas[0].pk}") == pk(target)

    def test_price_range_and_ordering(self, ids):
        cheap, mid, dear = (ItemFactory(unit_price=Decimal(p)) for p in (1000, 2000, 3000))
        assert ids(f"{ITEMS_URL}?min_price=2000&max_price=2000") == pk(mid)
        assert ids(f"{ITEMS_URL}?ordering=unit_price") == pk(cheap, mid, dear)
        assert ids(f"{ITEMS_URL}?ordering=-unit_price") == pk(dear, mid, cheap)

    def test_search(self, ids):
        pilau = ItemFactory(name="Pilau ya Nyama")
        ItemFactory(name="Chipsi")
        assert ids(f"{ITEMS_URL}?search=pilau") == pk(pilau)
        # The same search backs the Phase 4 assistant.
        assert list(services.search_items("PILAU")) == [pilau]
        hidden = ItemFactory(name="Pilau kuku", is_available=False)
        assert hidden not in services.search_items("pilau")


class TestPackageFilters:
    def test_contains_alcohol_and_filters_do_not_duplicate(self, ids, api_client):
        vendor = VendorProfileFactory()
        category = CategoryFactory(kind="drink", slug="bia")
        beers = ItemFactory.create_batch(
            2, vendor=vendor, kind="drink", is_alcoholic=True, category=category
        )
        party = PackageFactory(vendor=vendor, items=beers)
        dry = PackageFactory(vendor=vendor, items=[ItemFactory(vendor=vendor)])
        assert ids(f"{PACKAGES_URL}?is_alcoholic=true") == pk(party)
        assert ids(f"{PACKAGES_URL}?is_alcoholic=false") == pk(dry)
        assert ids(f"{PACKAGES_URL}?kind=drink") == pk(party)
        assert ids(f"{PACKAGES_URL}?category=bia") == pk(party)
        assert api_client.get(f"{PACKAGES_URL}{party.pk}/").json()["contains_alcohol"] is True
        assert api_client.get(f"{PACKAGES_URL}{dry.pk}/").json()["contains_alcohol"] is False

    def test_price_vendor_area_search(self, ids):
        areas = ServiceAreaFactory.create_batch(2)
        target = PackageFactory(
            name="Harusi Kubwa", price=Decimal("50000"), vendor__service_areas=areas
        )
        other = PackageFactory()
        assert ids(f"{PACKAGES_URL}?min_price=40000") == pk(target)
        assert ids(f"{PACKAGES_URL}?max_price=40000") == pk(other)
        assert ids(f"{PACKAGES_URL}?vendor={target.vendor.pk}") == pk(target)
        assert ids(f"{PACKAGES_URL}?service_area={areas[1].pk}") == pk(target)
        assert ids(f"{PACKAGES_URL}?search=harusi") == pk(target)
        assert ids(f"{PACKAGES_URL}?ordering=price") == pk(other, target)


def test_categories_public_and_filterable(api_client):
    body = api_client.get(f"{CATEGORIES_URL}?kind=drink").json()
    assert body["count"] > 0
    assert {c["kind"] for c in body["results"]} == {"drink"}
    assert {"name_en", "name_sw", "slug"} <= set(body["results"][0])

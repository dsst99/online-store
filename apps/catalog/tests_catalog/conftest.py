import pytest
from django.core.cache import cache
from rest_framework.test import APIClient

from apps.catalog.models import Category, Product


@pytest.fixture(autouse=True)
def clear_cache():
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture
def category(db):
    return Category.objects.create(name="Electronics", slug="electronics", is_active=True)


@pytest.fixture
def inactive_category(db):
    return Category.objects.create(name="Archive", slug="archive", is_active=False)


@pytest.fixture
def product(db, category):
    return Product.objects.create(
        name="Phone X",
        description="Test phone",
        price=999.99,
        stock=10,
        category=category,
        is_active=True,
    )


@pytest.fixture
def inactive_product(db, category):
    return Product.objects.create(
        name="Old Phone",
        description="Old",
        price=10,
        stock=0,
        category=category,
        is_active=False,
    )

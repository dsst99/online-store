import pytest
from django.urls import reverse
from apps.catalog.models import Product


@pytest.mark.django_db
def test_product_list_filters_and_cache_version_bump(api_client, product):
    url = reverse("products-list")

    # Базовый запрос -> MISS
    r1 = api_client.get(url)
    assert r1.status_code == 200
    assert r1["X-Cache"] == "MISS"
    assert any(p["name"] == "Phone X" for p in r1.json())

    # Повтор -> HIT
    r2 = api_client.get(url)
    assert r2.status_code == 200
    assert r2["X-Cache"] == "HIT"

    # Фильтр по category id
    r3 = api_client.get(url, {"category": product.category_id})
    assert r3.status_code == 200
    assert all(p["name"] == "Phone X" for p in r3.json())

    # Фильтр по slug
    r4 = api_client.get(url, {"category_slug": product.category.slug})
    assert r4.status_code == 200
    assert all(p["name"] == "Phone X" for p in r4.json())

    # price_min / price_max
    assert api_client.get(url, {"price_min": "900"}).status_code == 200
    assert api_client.get(url, {"price_max": "1000"}).status_code == 200

    # --- проверяем версионирование списка (сигналы инкрементируют версию) ---
    # Изменяем продукт (post_save триггерит _incr_version("products:list:version"))
    product.price = 888
    product.save()

    # После изменения — новый ключ (vN+1) => MISS
    r_after = api_client.get(url)
    assert r_after.status_code == 200
    assert r_after["X-Cache"] == "MISS"


@pytest.mark.django_db
def test_product_detail_active_vs_inactive(api_client, product, inactive_product):
    # активный -> 200
    url_ok = reverse("products-detail", kwargs={"pk": product.id})
    r_ok = api_client.get(url_ok)
    assert r_ok.status_code == 200
    assert r_ok["X-Cache"] in ("MISS", "HIT")
    data = r_ok.json()
    assert data["id"] == product.id
    assert data["name"] == product.name

    # неактивный -> 404
    url_inactive = reverse("products-detail", kwargs={"pk": inactive_product.id})
    r_inactive = api_client.get(url_inactive)
    assert r_inactive.status_code == 404

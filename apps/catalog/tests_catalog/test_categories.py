import pytest
from django.urls import reverse
from apps.catalog.models import Category, Product


@pytest.mark.django_db
def test_category_list_cache_hit_miss_and_search(api_client, category):
    url = reverse("categories-list")

    # 1-й запрос -> MISS
    r1 = api_client.get(url)
    assert r1.status_code == 200
    assert r1["X-Cache"] == "MISS"
    assert any(c["slug"] == "electronics" for c in r1.json())

    # 2-й запрос теми же параметрами -> HIT
    r2 = api_client.get(url)
    assert r2.status_code == 200
    assert r2["X-Cache"] == "HIT"

    # поиск по name
    r3 = api_client.get(url, {"search": "Elect"})
    assert r3.status_code == 200
    data = r3.json()
    assert any("Electronics" in c["name"] for c in data)


@pytest.mark.django_db
def test_category_detail_active_vs_inactive(api_client, category, inactive_category):
    # активная -> 200
    url_ok = reverse("categories-detail", kwargs={"pk": category.id})
    r_ok = api_client.get(url_ok)
    assert r_ok.status_code == 200
    assert r_ok["X-Cache"] in ("MISS", "HIT")
    body = r_ok.json()
    assert body["id"] == category.id
    assert body["slug"] == "electronics"

    # неактивная -> 404
    url_inactive = reverse("categories-detail", kwargs={"pk": inactive_category.id})
    r_inactive = api_client.get(url_inactive)
    assert r_inactive.status_code == 404


@pytest.mark.django_db
def test_category_delete_soft_and_hard_constraints(admin_client, category):
    # soft delete (по умолчанию)
    url = reverse("categories-detail", kwargs={"pk": category.id})
    r_soft = admin_client.delete(url)  # без ?hard=true
    assert r_soft.status_code == 204
    category.refresh_from_db()
    assert category.is_active is False

    # создать новую категорию и продукт, чтобы проверить hard-ветку
    cat2 = Category.objects.create(name="Books", slug="books", is_active=True)
    Product.objects.create(
        name="Novel", description="n", price=5, stock=1, category=cat2, is_active=True
    )

    # hard delete должно вернуть 400 при наличии связанных продуктов
    url2 = reverse("categories-detail", kwargs={"pk": cat2.id})
    r_hard_blocked = admin_client.delete(url2 + "?hard=true")
    assert r_hard_blocked.status_code == 400
    assert r_hard_blocked.json().get("code") == "category_in_use"

    # удалим продукт и повторим hard delete
    Product.objects.filter(category=cat2).delete()
    r_hard_ok = admin_client.delete(url2 + "?hard=true")
    assert r_hard_ok.status_code == 204
    assert Category.objects.filter(pk=cat2.id).exists() is False

import pytest
from django.urls import reverse

from apps.orders.models import Order, OrderItem


@pytest.mark.django_db
def test_create_order_success_and_celery_called(api_client, products, monkeypatch):
    p1, p2 = products

    # замокаем Celery-задачи (delay)
    called = {"created": None, "shipped": None}

    def fake_created_delay(order_id):
        called["created"] = order_id

    def fake_shipped_delay(order_id):
        called["shipped"] = order_id

    import apps.orders.tasks as tasks
    monkeypatch.setattr(tasks.order_created_generate_pdf_and_email, "delay", fake_created_delay)
    monkeypatch.setattr(tasks.order_shipped_notify_external, "delay", fake_shipped_delay)

    url = reverse("orders-list")
    payload = {
        "items": [
            {"product_id": p1.id, "quantity": 2},
            {"product_id": p2.id, "quantity": 3},
            {"product_id": p1.id, "quantity": 1},  # дубликат — должен агрегироваться (итого p1: 3)
        ]
    }

    # создание
    r = api_client.post(url, payload, format="json")
    assert r.status_code == 201, r.json()
    data = r.json()
    order_id = data["id"]

    # проверим total и списание stock
    p1.refresh_from_db(); p2.refresh_from_db()
    assert p1.stock == 7  # 10 - 3
    assert p2.stock == 47 # 50 - 3
    assert float(data["total_price"]) == 3 * float(500) + 3 * float(20)

    # задача создания была вызвана
    assert called["created"] == order_id

    # список заказов пользователя: MISS -> HIT
    list_url = reverse("orders-list")
    r1 = api_client.get(list_url)
    assert r1.status_code == 200
    assert r1["X-Cache"] == "MISS"

    r2 = api_client.get(list_url)
    assert r2.status_code == 200
    assert r2["X-Cache"] == "HIT"

    # деталь заказа: MISS -> HIT
    detail_url = reverse("orders-detail", kwargs={"pk": order_id})
    d1 = api_client.get(detail_url)
    assert d1.status_code == 200
    assert d1["X-Cache"] == "MISS"

    d2 = api_client.get(detail_url)
    assert d2.status_code == 200
    assert d2["X-Cache"] == "HIT"


@pytest.mark.django_db
def test_create_order_insufficient_stock(api_client, products):
    p1, _ = products
    # сделаем заведомо большой запрос
    url = reverse("orders-list")
    payload = {"items": [{"product_id": p1.id, "quantity": p1.stock + 1}]}
    r = api_client.post(url, payload, format="json")
    assert r.status_code == 400
    body = r.json()
    assert "stock" in body
    assert "details" in body
    assert body["details"][0]["product_id"] == p1.id


@pytest.mark.django_db
def test_permissions_only_owner_can_view_order(api_client, other_client, products):
    p1, _ = products
    # создаём заказ от api_client
    create = api_client.post(reverse("orders-list"), {"items": [{"product_id": p1.id, "quantity": 1}]}, format="json")
    assert create.status_code == 201
    order_id = create.json()["id"]

    # другой пользователь не может видеть — 403
    resp = other_client.get(reverse("orders-detail", kwargs={"pk": order_id}))
    assert resp.status_code == 403


@pytest.mark.django_db
def test_status_transitions_and_shipped_task(api_client, products, monkeypatch):
    p1, _ = products

    # замокаем shipped-задачу
    shipped_called = {"order": None}
    import apps.orders.tasks as tasks
    monkeypatch.setattr(tasks.order_shipped_notify_external, "delay", lambda oid: shipped_called.__setitem__("order", oid))

    # создаём заказ
    create = api_client.post(reverse("orders-list"), {"items": [{"product_id": p1.id, "quantity": 1}]}, format="json")
    assert create.status_code == 201
    order_id = create.json()["id"]

    # pending -> processing
    patch1 = api_client.patch(reverse("orders-detail", kwargs={"pk": order_id}), {"status": "processing"}, format="json")
    assert patch1.status_code == 200
    assert patch1.json()["status"] == "processing"

    # processing -> shipped (должна дёрнуться задача)
    patch2 = api_client.patch(reverse("orders-detail", kwargs={"pk": order_id}), {"status": "shipped"}, format="json")
    assert patch2.status_code == 200
    assert patch2.json()["status"] == "shipped"
    assert shipped_called["order"] == order_id

    # shipped -> pending (запрещено)
    patch_bad = api_client.patch(reverse("orders-detail", kwargs={"pk": order_id}), {"status": "pending"}, format="json")
    assert patch_bad.status_code == 400


@pytest.mark.django_db
def test_admin_orders_list_filters(admin_client, api_client, products):
    p1, _ = products

    # создадим 2 заказа от текущего юзера
    for _ in range(2):
        r = api_client.post(reverse("orders-list"), {"items": [{"product_id": p1.id, "quantity": 1}]}, format="json")
        assert r.status_code == 201

    # админский список: MISS -> HIT и фильтрация по статусу
    url = reverse("admin-orders-list")

    q1 = admin_client.get(url, {"status": "pending"})
    assert q1.status_code == 200
    assert q1["X-Cache"] == "MISS"

    q2 = admin_client.get(url, {"status": "pending"})
    assert q2.status_code == 200
    assert q2["X-Cache"] == "HIT"

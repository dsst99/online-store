import pytest
from django.urls import reverse
from rest_framework.test import APIClient


@pytest.mark.django_db
def test_register_login_refresh_and_protected_access(client):
    # 1) register
    r1 = client.post(
        reverse("auth-register"),
        {"username": "u1", "email": "u1@example.com", "password": "StrongPass123!"},
        content_type="application/json",
    )
    assert r1.status_code == 201, r1.content
    body = r1.json()
    assert body["email"] == "u1@example.com"
    assert "id" in body

    # 2) login -> получаем access/refresh
    r2 = client.post(
        reverse("auth-login"),
        {"username": "u1", "password": "StrongPass123!"},
        content_type="application/json",
    )
    assert r2.status_code == 200, r2.content
    tokens = r2.json()
    assert "access" in tokens and "refresh" in tokens

    # 3) доступ к защищённому эндпоинту (orders-list) с access токеном
    api = APIClient()
    api.credentials(HTTP_AUTHORIZATION=f"Bearer {tokens['access']}")
    r3 = api.get(reverse("orders-list"))
    assert r3.status_code == 200

    # 4) refresh -> новый access
    r4 = client.post(
        reverse("auth-refresh"),
        {"refresh": tokens["refresh"]},
        content_type="application/json",
    )
    assert r4.status_code == 200, r4.content
    new_access = r4.json().get("access")
    assert new_access and new_access != tokens["access"]


@pytest.mark.django_db
def test_orders_requires_auth(client):
    # Без токена к защищённому эндпоинту доступа нет
    r = client.get(reverse("orders-list"))
    assert r.status_code in (401, 403)

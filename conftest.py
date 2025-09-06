# conftest.py — в корне проекта
import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

User = get_user_model()

@pytest.fixture
def user(db):
    return User.objects.create_user(
        username="user1",
        email="user1@example.com",
        password="Passw0rd!user1",
    )

@pytest.fixture
def other_user(db):
    return User.objects.create_user(
        username="user2",
        email="user2@example.com",
        password="Passw0rd!user2",
    )

@pytest.fixture
def admin_user(db):
    return User.objects.create_user(
        username="admin",
        email="admin@example.com",
        password="Passw0rd!admin",
        is_staff=True,
        is_superuser=True,
    )

@pytest.fixture
def api_client(user):
    client = APIClient()
    client.force_authenticate(user)
    return client

@pytest.fixture
def other_client(other_user):
    client = APIClient()
    client.force_authenticate(other_user)
    return client

@pytest.fixture
def admin_client(admin_user):
    client = APIClient()
    client.force_authenticate(admin_user)
    return client

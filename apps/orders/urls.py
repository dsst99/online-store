from django.urls import path
from .views import (
    OrderListCreateView,
    OrderDetailView,
    AdminOrderListView,
)

urlpatterns = [
    # заказы пользователя
    path("orders/", OrderListCreateView.as_view(), name="orders-list"),
    path("orders/<int:pk>/", OrderDetailView.as_view(), name="orders-detail"),

    # админский список заказов
    path("admin/orders/", AdminOrderListView.as_view(), name="admin-orders-list"),
]

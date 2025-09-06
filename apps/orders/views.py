import hashlib
import random
from urllib.parse import urlencode

from django.core.cache import cache
from django.shortcuts import get_object_or_404
from rest_framework import generics, permissions, filters, status
from rest_framework.response import Response

from apps.orders.models import Order
from apps.orders.serializers import (
    OrderCreateSerializer,
    OrderListSerializer,
    OrderDetailSerializer,
    OrderStatusPatchSerializer,
    PlainBadRequest
)


# ---------- cache utils ----------

def _ttl_with_jitter(base: int = 60, jitter: float = 0.10) -> int:
    delta = int(base * jitter)
    return base + random.randint(-delta, delta)


def _hash_params(params: dict) -> str:
    encoded = urlencode(sorted(params.items()), doseq=True)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _orders_user_list_version() -> int:
    v = cache.get("orders:user:list:version")
    return v if isinstance(v, int) and v > 0 else 1


def _orders_admin_list_version() -> int:
    v = cache.get("orders:admin:list:version")
    return v if isinstance(v, int) and v > 0 else 1


# ---------- permissions ----------

class IsOwnerOrAdmin(permissions.BasePermission):
    def has_object_permission(self, request, view, obj: Order):
        return request.user.is_staff or obj.user_id == request.user.id


# ---------- user endpoints ----------

class OrderListCreateView(generics.GenericAPIView):
    """
    GET /api/v1/orders/         — список заказов текущего пользователя (кэш 60с)
    POST /api/v1/orders/        — создание заказа (см. OrderCreateSerializer)
    """
    permission_classes = [permissions.IsAuthenticated]
    filter_backends = [filters.OrderingFilter]
    ordering_fields = ["created_at", "total_price", "status"]
    ordering = ["-created_at"]

    def get_queryset(self):
        return (
            Order.objects.filter(user=self.request.user)
            .only("id", "status", "total_price", "created_at", "updated_at", "user_id")
            .order_by(*self.ordering)
        )

    def get(self, request, *args, **kwargs):
        """кэш ключ с версией + user + ordering/pagination"""
        params = {
            "ordering": ",".join(request.query_params.getlist("ordering")) or "-created_at",
            "page": request.query_params.get("page", ""),
            "page_size": request.query_params.get("page_size", ""),
        }
        version = _orders_user_list_version()
        cache_key = f"orders:list:user:{request.user.id}:v{version}:{_hash_params(params)}"

        cached = cache.get(cache_key)
        if cached is not None:
            resp = Response(cached)
            resp["X-Cache"] = "HIT"
            return resp

        qs = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(qs)
        if page is not None:
            data = OrderListSerializer(page, many=True).data
            cache.set(cache_key, data, timeout=_ttl_with_jitter())
            resp = self.get_paginated_response(data)
            resp["X-Cache"] = "MISS"
            return resp

        data = OrderListSerializer(qs, many=True).data
        cache.set(cache_key, data, timeout=_ttl_with_jitter())
        resp = Response(data)
        resp["X-Cache"] = "MISS"
        return resp

    def post(self, request, *args, **kwargs):
        ser = OrderCreateSerializer(data=request.data, context={"request": request})
        ser.is_valid(raise_exception=True)
        try:
            order = ser.save()
        except PlainBadRequest as e:
            return Response(e.payload, status=status.HTTP_400_BAD_REQUEST)
        # деталь в ответе
        data = OrderDetailSerializer(order).data
        # инвалидация списка пользователя (версия поднимет сигнал — см. orders/signals.py)
        return Response(data, status=status.HTTP_201_CREATED)


class OrderDetailView(generics.GenericAPIView):
    """
    GET    /api/v1/orders/{id}/    — детальная информация (владелец/админ, кэш 60с)
    PATCH  /api/v1/orders/{id}/    — обновление статуса (владелец ограниченно/админ)
    """
    permission_classes = [permissions.IsAuthenticated, IsOwnerOrAdmin]

    def get_object(self):
        order = get_object_or_404(Order.objects.select_related("user"), pk=self.kwargs["pk"])
        self.check_object_permissions(self.request, order)
        return order

    def get(self, request, *args, **kwargs):
        pk = kwargs["pk"]
        cache_key = f"order:{pk}"
        cached = cache.get(cache_key)
        if cached is not None:
            resp = Response(cached)
            resp["X-Cache"] = "HIT"
            return resp

        obj = self.get_object()
        data = OrderDetailSerializer(obj).data
        cache.set(cache_key, data, timeout=_ttl_with_jitter())
        resp = Response(data)
        resp["X-Cache"] = "MISS"
        return resp

    def patch(self, request, *args, **kwargs):
        obj = self.get_object()
        ser = OrderStatusPatchSerializer(obj, data=request.data, partial=True)
        ser.is_valid(raise_exception=True)
        ser.save()
        # инвалидация детали (сигналы тоже почистят, но сразу ответим актуальными данными)
        data = OrderDetailSerializer(obj).data
        cache.set(f"order:{obj.pk}", data, timeout=_ttl_with_jitter())
        return Response(data, status=status.HTTP_200_OK)


# ---------- admin endpoints ----------

class AdminOrderListView(generics.GenericAPIView):
    """
    GET /api/v1/admin/orders/
    Фильтры: ?status=...&user=<id>&date_from=YYYY-MM-DD&date_to=YYYY-MM-DD
    Кэш: 60с, версия admin-листа.
    """
    permission_classes = [permissions.IsAdminUser]
    filter_backends = [filters.OrderingFilter]
    ordering_fields = ["created_at", "total_price", "status", "user_id"]
    ordering = ["-created_at"]

    def get_queryset(self):
        qs = Order.objects.all().order_by(*self.ordering)
        status_val = self.request.query_params.get("status")
        user_id = self.request.query_params.get("user")
        date_from = self.request.query_params.get("date_from")
        date_to = self.request.query_params.get("date_to")

        if status_val:
            qs = qs.filter(status=status_val)
        if user_id:
            qs = qs.filter(user_id=user_id)
        if date_from:
            qs = qs.filter(created_at__date__gte=date_from)
        if date_to:
            qs = qs.filter(created_at__date__lte=date_to)
        return qs

    def get(self, request, *args, **kwargs):
        params = {
            "status": request.query_params.get("status", ""),
            "user": request.query_params.get("user", ""),
            "date_from": request.query_params.get("date_from", ""),
            "date_to": request.query_params.get("date_to", ""),
            "ordering": ",".join(request.query_params.getlist("ordering")) or "-created_at",
            "page": request.query_params.get("page", ""),
            "page_size": request.query_params.get("page_size", ""),
        }
        version = _orders_admin_list_version()
        cache_key = f"admin:orders:list:v{version}:{_hash_params(params)}"

        cached = cache.get(cache_key)
        if cached is not None:
            resp = Response(cached)
            resp["X-Cache"] = "HIT"
            return resp

        qs = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(qs)
        if page is not None:
            data = OrderListSerializer(page, many=True).data
            cache.set(cache_key, data, timeout=_ttl_with_jitter())
            resp = self.get_paginated_response(data)
            resp["X-Cache"] = "MISS"
            return resp

        data = OrderListSerializer(qs, many=True).data
        cache.set(cache_key, data, timeout=_ttl_with_jitter())
        resp = Response(data)
        resp["X-Cache"] = "MISS"
        return resp

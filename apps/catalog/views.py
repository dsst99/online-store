import hashlib
import random
from urllib.parse import urlencode

from django.core.cache import cache
from django.db.models.functions import Lower
from django.shortcuts import get_object_or_404

from rest_framework import status, generics, permissions, filters
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle, UserRateThrottle
from django_filters.rest_framework import DjangoFilterBackend

from apps.catalog.models import Category, Product
from apps.catalog.serializers import (
    CategoryListSerializer,
    CategoryDetailSerializer,
    ProductListSerializer, ProductDetailSerializer,
)


# ---------- cache utils ----------

def _ttl_with_jitter(base: int = 300, jitter: float = 0.10) -> int:
    """TTL с анти-догпайлом: ±jitter от базового значения (по умолчанию ±10%)."""
    delta = int(base * jitter)
    return base + random.randint(-delta, delta)


def _hash_params(params: dict) -> str:
    """Стабильный sha256-хэш нормализованных параметров запроса (для ключей кэша)."""
    encoded = urlencode(sorted(params.items()), doseq=True)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _products_list_version() -> int:
    """
    Версия списков продуктов для кэша.
    Инкрементируется сигналами при create/update/delete/soft_delete Product.
    Если версии нет — инициализируем 1 (см. сигнал).
    """
    key = "products:list:version"
    v = cache.get(key)
    return v if isinstance(v, int) and v > 0 else 1


def _categories_list_version() -> int:
    key = "categories:list:version"
    v = cache.get(key)
    return v if isinstance(v, int) and v > 0 else 1


# ---------- throttling ----------

class AnonCatalogThrottle(AnonRateThrottle):
    """Троттлинг для анонимных пользователей каталога."""
    rate = "60/min"


class UserCatalogThrottle(UserRateThrottle):
    """Троттлинг для аутентифицированных пользователей каталога."""
    rate = "240/min"


# ---------- categories ----------

class CategoryListView(generics.ListAPIView):
    """
    GET /api/v1/categories/
    Назначение:
      - вернуть список активных категорий.
    Функционал:
      - поиск по name (?search=..., регистр не важен);
      - ручной кэш Memcached с ключом, учитывающим параметры;
      - заголовок X-Cache: HIT|MISS.
    """
    serializer_class = CategoryListSerializer
    throttle_classes = [AnonCatalogThrottle, UserCatalogThrottle]
    filter_backends = [filters.SearchFilter]
    search_fields = ['name']
    pagination_class = None  # по ТЗ: без пагинации

    def get_queryset(self):
        return Category.objects.filter(is_active=True).order_by(Lower('name'))

    def list(self, request, *args, **kwargs):
        # нормализуем параметры для ключа кэша
        params = {
            "search": (request.query_params.get("search") or "").strip().lower(),
        }
        version = _categories_list_version()
        cache_key = f"categories:list:v{version}:{_hash_params(params)}"

        cached = cache.get(cache_key)
        if cached is not None:
            resp = Response(cached)
            resp["X-Cache"] = "HIT"
            return resp

        queryset = self.filter_queryset(self.get_queryset())
        serializer = self.get_serializer(queryset, many=True)
        data = serializer.data

        cache.set(cache_key, data, timeout=_ttl_with_jitter(300, 0.10))
        resp = Response(data)
        resp["X-Cache"] = "MISS"
        return resp


class CategoryView(generics.RetrieveAPIView):
    """
    GET /api/v1/categories/{id}/
    DELETE /api/v1/categories/{id}/
    Назначение:
      - GET: вернуть детальную информацию по категории (public).
      - DELETE: удалить категорию (по умолчанию мягко) — только админ.
    Правила:
      - GET: неактивные (is_active=False) не выдаём → 404.
      - DELETE: по умолчанию soft (is_active=False); hard — только с ?hard=true и если нет связанных продуктов.
    Кэш:
      - GET: ключ category:{id}, TTL 5 минут ±10%, X-Cache: HIT|MISS.
    """
    serializer_class = CategoryDetailSerializer
    throttle_classes = [AnonCatalogThrottle, UserCatalogThrottle]
    lookup_field = "pk"

    def get_permissions(self):
        if self.request.method == "DELETE":
            return [permissions.IsAdminUser()]
        return super().get_permissions()

    def get(self, request, *args, **kwargs):
        pk = kwargs.get("pk")
        cache_key = f"category:{pk}"
        cached = cache.get(cache_key)
        if cached is not None:
            resp = Response(cached)
            resp["X-Cache"] = "HIT"
            return resp
        instance = get_object_or_404(Category, pk=pk, is_active=True)
        data = self.get_serializer(instance).data
        cache.set(cache_key, data, timeout=_ttl_with_jitter(300, 0.10))
        resp = Response(data)
        resp["X-Cache"] = "MISS"
        return resp

    def delete(self, request, pk, *args, **kwargs):
        category = get_object_or_404(Category, pk=pk)
        hard = str(request.query_params.get("hard", "false")).lower() in ("1", "true", "yes")
        if hard:
            if category.products.exists():
                return Response(
                    {"detail": "Категория содержит продукты, удаление невозможно", "code": "category_in_use"},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            category.delete()
            return Response(status=status.HTTP_204_NO_CONTENT)
        category.soft_delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


# ---------- products ----------

class ProductListView(generics.ListAPIView):
    """
    GET /api/v1/products/
    Назначение:
      - вернуть список активных продуктов.
    Функционал:
      - поиск по name (?search=..., регистр не важен);
      - фильтры:
          * ?category=<id>  ИЛИ  ?category_slug=<slug>
          * ?price_min=<num> (price__gte)
          * ?price_max=<num> (price__lte)
      - сортировка по name (ASC);
      - ручной кэш Memcached: ключ = products:list:v{N}:{hash(filters)}, TTL 5 минут ±10%;
      - заголовок X-Cache: HIT|MISS.
    Ответ (по текущему сериализатору):
      - [{id, name, price, category}] — category = имя категории.
    """
    throttle_classes = [AnonCatalogThrottle, UserCatalogThrottle]
    serializer_class = ProductListSerializer
    filter_backends = [filters.SearchFilter, DjangoFilterBackend]
    search_fields = ['name']
    pagination_class = None  # без пагинации

    def get_queryset(self):
        """
        Базовый queryset:
          - только активные товары,
          - подгружаем категорию (select_related) чтобы не было N+1,
          - сортируем по name.
        """
        return (
            Product.objects.filter(is_active=True)
            .select_related('category')
            .order_by(Lower('name'))
        )

    def list(self, request, *args, **kwargs):
        # Собираем и нормализуем параметры фильтрации/поиска для ключа кэша
        search = (request.query_params.get("search") or "").strip().lower()
        category_id = (request.query_params.get("category") or "").strip()
        category_slug = (request.query_params.get("category_slug") or "").strip().lower()
        price_min = (request.query_params.get("price_min") or "").strip()
        price_max = (request.query_params.get("price_max") or "").strip()

        version = _products_list_version()
        params = {
            "search": search,
            "category": category_id,
            "category_slug": category_slug,
            "price_min": price_min,
            "price_max": price_max,
        }
        cache_key = f"products:list:v{version}:{_hash_params(params)}"

        cached = cache.get(cache_key)
        if cached is not None:
            resp = Response(cached)
            resp["X-Cache"] = "HIT"
            return resp

        # Применяем фильтры к queryset
        qs = self.get_queryset()
        if category_id:
            qs = qs.filter(category_id=category_id)
        if category_slug:
            qs = qs.filter(category__slug=category_slug)
        if price_min:
            try:
                qs = qs.filter(price__gte=price_min)
            except Exception:
                pass  # игнорируем некорректный параметр, не падаем
        if price_max:
            try:
                qs = qs.filter(price__lte=price_max)
            except Exception:
                pass

        # Поиск по имени через SearchFilter
        qs = self.filter_queryset(qs)

        serializer = self.get_serializer(qs, many=True)
        data = serializer.data
        cache.set(cache_key, data, timeout=_ttl_with_jitter(300, 0.10))

        resp = Response(data)
        resp["X-Cache"] = "MISS"
        return resp


class ProductDetailView(generics.RetrieveAPIView):
    """
    GET /api/v1/products/{id}/
    Назначение:
      - вернуть детальную информацию по продукту.
    Правила:
      - неактивные продукты (is_active=False) в публичном API не выдаём → 404.
    Кэш:
      - ключ: product:{id}, TTL 5 минут ±10%, заголовок X-Cache: HIT|MISS.
    """
    serializer_class = ProductDetailSerializer
    throttle_classes = [AnonCatalogThrottle, UserCatalogThrottle]
    lookup_field = "pk"

    def retrieve(self, request, *args, **kwargs):
        pk = kwargs.get("pk")
        cache_key = f"product:{pk}"

        cached = cache.get(cache_key)
        if cached is not None:
            resp = Response(cached)
            resp["X-Cache"] = "HIT"
            return resp

        # Публичный контракт: неактивные продукты в публичном API не выдаём
        instance = get_object_or_404(Product.objects.select_related("category"), pk=pk, is_active=True)

        serializer = self.get_serializer(instance)
        data = serializer.data
        cache.set(cache_key, data, timeout=_ttl_with_jitter(300, 0.10))

        resp = Response(data)
        resp["X-Cache"] = "MISS"
        return resp

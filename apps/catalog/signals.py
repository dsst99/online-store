from django.core.cache import cache
from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver

from apps.catalog.models import Product, Category


# ---- утилиты для версий списков ----

def _incr_version(key: str, initial: int = 1) -> None:
    """
    Атомарно инкрементируем версию списка в Memcached.
    Если ключа нет — создаём с initial, затем инкрементируем.
    """
    cache.add(key, initial)  # если ключа нет — создаём
    try:
        cache.incr(key)
    except Exception:
        current = cache.get(key) or initial
        cache.set(key, int(current) + 1)


# ---- Category: инвалидация ----

@receiver(post_save, sender=Category, dispatch_uid="category_saved_cache_invalidation")
def category_saved(sender, instance: Category, **kwargs):
    # Сбрасываем деталь
    cache.delete(f"category:{instance.pk}")
    # Инкремент версии списков категорий (используется в ключе CategoryListView)
    _incr_version("categories:list:version")


@receiver(post_delete, sender=Category, dispatch_uid="category_deleted_cache_invalidation")
def category_deleted(sender, instance: Category, **kwargs):
    cache.delete(f"category:{instance.pk}")
    _incr_version("categories:list:version")


# ---- Product: инвалидация ----

@receiver(post_save, sender=Product, dispatch_uid="product_saved_cache_invalidation")
def product_saved(sender, instance: Product, **kwargs):
    # Деталь продукта (используется в ProductDetailView)
    cache.delete(f"product:{instance.pk}")
    # Инкремент версии списков продуктов (используется в ключе ProductListView)
    _incr_version("products:list:version")


@receiver(post_delete, sender=Product, dispatch_uid="product_deleted_cache_invalidation")
def product_deleted(sender, instance: Product, **kwargs):
    cache.delete(f"product:{instance.pk}")
    _incr_version("products:list:version")

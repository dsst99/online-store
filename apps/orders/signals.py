from django.core.cache import cache
from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver

from apps.orders.models import Order, OrderItem


def _incr_version(key: str, initial: int = 1) -> None:
    """Атомарно инкрементируем версию кэш-списков (fallback для backends без incr)."""
    cache.add(key, initial)
    try:
        cache.incr(key)
    except Exception:
        current = cache.get(key) or initial
        cache.set(key, int(current) + 1)


def _bump_user_admin_lists(order: Order):
    """Поднять версии пользовательских и админских списков после изменений заказа/состава."""
    # список конкретного пользователя (учитывается в ключе OrderListCreateView)
    _incr_version("orders:user:list:version")
    # общий админский список (AdminOrderListView)
    _incr_version("orders:admin:list:version")


# -------- Order: инвалидация --------

@receiver(post_save, sender=Order, dispatch_uid="order_saved_cache_invalidation")
def order_saved(sender, instance: Order, **kwargs):
    # чистим деталь
    cache.delete(f"order:{instance.pk}")
    # bump списков
    _bump_user_admin_lists(instance)


@receiver(post_delete, sender=Order, dispatch_uid="order_deleted_cache_invalidation")
def order_deleted(sender, instance: Order, **kwargs):
    cache.delete(f"order:{instance.pk}")
    _bump_user_admin_lists(instance)


# -------- OrderItem: инвалидация --------

@receiver(post_save, sender=OrderItem, dispatch_uid="orderitem_saved_cache_invalidation")
def orderitem_saved(sender, instance: OrderItem, **kwargs):
    # изменение состава влияет на деталь заказа + списки
    cache.delete(f"order:{instance.order_id}")
    _bump_user_admin_lists(instance.order)


@receiver(post_delete, sender=OrderItem, dispatch_uid="orderitem_deleted_cache_invalidation")
def orderitem_deleted(sender, instance: OrderItem, **kwargs):
    cache.delete(f"order:{instance.order_id}")
    _bump_user_admin_lists(instance.order)

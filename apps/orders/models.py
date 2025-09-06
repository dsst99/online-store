from decimal import Decimal

from django.db import models
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db.models import F, Sum, DecimalField, Value
from django.db.models.functions import Coalesce

from apps.catalog.models import Product  # важно: используем каталог

User = get_user_model()


class Order(models.Model):
    STATUS_PENDING = 'pending'
    STATUS_PROCESSING = 'processing'
    STATUS_SHIPPED = 'shipped'
    STATUS_DELIVERED = 'delivered'
    STATUS_CANCELLED = 'cancelled'

    STATUS_CHOICES = [
        (STATUS_PENDING, 'Pending'),
        (STATUS_PROCESSING, 'Processing'),
        (STATUS_SHIPPED, 'Shipped'),
        (STATUS_DELIVERED, 'Delivered'),
        (STATUS_CANCELLED, 'Cancelled'),
    ]

    user = models.ForeignKey(User, on_delete=models.PROTECT, related_name='orders')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING)
    total_price = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    products = models.ManyToManyField(Product, through='OrderItem', related_name='orders')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user']),
            models.Index(fields=['status', '-created_at']),
        ]

    def clean(self):
        """Валидируем переход статуса и инварианты."""
        valid_transitions = {
            self.STATUS_PENDING: [self.STATUS_PROCESSING, self.STATUS_CANCELLED],
            self.STATUS_PROCESSING: [self.STATUS_SHIPPED, self.STATUS_CANCELLED],
            self.STATUS_SHIPPED: [self.STATUS_DELIVERED],
            self.STATUS_DELIVERED: [],
            self.STATUS_CANCELLED: [],
        }
        if self.pk:
            old_status = type(self).objects.only('status').get(pk=self.pk).status
            if self.status != old_status and self.status not in valid_transitions[old_status]:
                raise ValidationError(f"Невозможно изменить статус {old_status} → {self.status}")

        if self.total_price < 0:
            raise ValidationError("total_price не может быть меньше 0")

    def recalc_total(self, save: bool = True):
        """Пересчёт total_price: Σ(quantity * price_at_purchase)."""
        agg = self.items.aggregate(
            s=Coalesce(
                Sum(
                    F('quantity') * F('price_at_purchase'),
                    output_field=DecimalField(max_digits=10, decimal_places=2),
                ),
                Value(Decimal('0.00'), output_field=DecimalField(max_digits=10, decimal_places=2)),
            )
        )
        self.total_price = agg['s']
        if save:
            # избегаем рекурсии save↔items: сохраняем только поле total_price
            type(self).objects.filter(pk=self.pk).update(total_price=self.total_price)

    def save(self, *args, **kwargs):
        """
        Сохраняем заказ. total не считаем до появления items.
        Рекомендованная последовательность в сервисе:
          1) создать Order
          2) создать OrderItem(...)
          3) order.recalc_total()
        """
        super().save(*args, **kwargs)

    @property
    def is_readonly(self):
        return self.status in {self.STATUS_SHIPPED, self.STATUS_DELIVERED, self.STATUS_CANCELLED}


class OrderItem(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name='items')
    product = models.ForeignKey(Product, on_delete=models.PROTECT)
    quantity = models.PositiveIntegerField(default=1)
    price_at_purchase = models.DecimalField(max_digits=8, decimal_places=2)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['order', 'product'], name='uniq_order_product'),
            models.CheckConstraint(condition=models.Q(quantity__gt=0), name='quantity_gt_0'),
            models.CheckConstraint(condition=models.Q(price_at_purchase__gte=0), name='price_at_purchase_gte_0'),
        ]
        indexes = [
            models.Index(fields=['order']),
            models.Index(fields=['product']),
        ]

    def clean(self):
        """Запрет изменений состава, если статус финальный."""
        if self.order.is_readonly:
            raise ValidationError("Нельзя изменять состав заказа после отправки/доставки/отмены")

    def save(self, *args, **kwargs):
        is_create = self._state.adding
        if is_create:
            # проставляем цену покупки, если не задана
            if self.price_at_purchase is None:
                self.price_at_purchase = self.product.price
        else:
            # запрещаем менять «исторические» поля
            old = type(self).objects.only('product_id', 'price_at_purchase').get(pk=self.pk)
            if self.product_id != old.product_id:
                raise ValidationError("Нельзя менять продукт в существующей позиции заказа")
            if self.price_at_purchase != old.price_at_purchase:
                raise ValidationError("Нельзя менять price_at_purchase в существующей позиции заказа")

        super().save(*args, **kwargs)

        # после изменения состава — пересчитать total заказа
        # (делаем только если у order уже есть pk)
        if self.order_id:
            self.order.recalc_total(save=True)

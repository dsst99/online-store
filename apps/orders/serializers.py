from collections import defaultdict

from django.db import transaction
from django.db.models import F
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers

from apps.catalog.models import Product
from apps.orders.models import Order, OrderItem
from apps.orders import tasks


# ---------- ВСПОМОГАТЕЛЬНЫЕ ----------

class OrderItemInputSerializer(serializers.Serializer):
    """Входная позиция при создании заказа."""
    product_id = serializers.IntegerField(min_value=1)
    quantity = serializers.IntegerField(min_value=1)

    def validate(self, attrs):
        return attrs  # базовая нормализация


class PlainBadRequest(Exception):
    """Исключение с готовым JSON-пейлоудом, который вернём из вью как есть."""

    def __init__(self, payload: dict):
        self.payload = payload


class OrderItemReadSerializer(serializers.ModelSerializer):
    """Позиция заказа (для чтения)."""
    product_name = serializers.CharField(source="product.name", read_only=True)

    class Meta:
        model = OrderItem
        fields = ("id", "product", "product_name", "quantity", "price_at_purchase", "created_at")
        read_only_fields = fields


# ---------- СОЗДАНИЕ ЗАКАЗА ----------

class OrderCreateSerializer(serializers.Serializer):
    """
    Создание заказа:
      - принимает список позиций [{product_id, quantity}, ...]
      - агрегирует дубликаты product_id
      - в транзакции: select_for_update по продуктам, проверка stock, списание, создание Order + OrderItem[]
      - пересчитывает total_price через order.recalc_total()
      - триггерит Celery-задачу генерации PDF и "отправки" email
    """
    items = OrderItemInputSerializer(many=True)

    def validate_items(self, items):
        if not items:
            raise serializers.ValidationError("Список позиций пуст.")
        aggregated = defaultdict(int)
        for it in items:
            aggregated[it["product_id"]] += it["quantity"]
        return [{"product_id": pid, "quantity": qty} for pid, qty in aggregated.items()]

    def create(self, validated_data):
        user = self.context["request"].user
        items = validated_data["items"]

        product_ids = [i["product_id"] for i in items]

        with transaction.atomic():
            # блокируем продукты для исключения гонок (уникальные id)
            products_qs = (
                Product.objects
                .select_for_update()
                .filter(pk__in=set(product_ids), is_active=True)
            )
            products_by_id = {p.id: p for p in products_qs}

            # проверяем, что все продукты существуют и активны
            missing = sorted(set(int(pid) for pid in product_ids) - set(products_by_id.keys()))
            if missing:
                raise PlainBadRequest({
                    "items": [f"Продукт(ы) не найдены или неактивны: {sorted(missing)}"]
                })

            # проверка stock
            errors = []
            for it in items:
                prod = products_by_id[it["product_id"]]
                requested = it["quantity"]
                if prod.stock < requested:
                    errors.append(
                        {"product_id": int(prod.pk), "available": int(prod.stock), "requested": int(requested)}
                    )
            if errors:
                raise PlainBadRequest({
                    "stock": "Недостаточно товара на складе",
                    "details": errors,
                })

            # создаём заказ
            order = Order.objects.create(user=user, status=Order.STATUS_PENDING)

            # списываем stock и создаём позиции
            order_items = []
            for it in items:
                prod = products_by_id[it["product_id"]]
                qty = it["quantity"]

                Product.objects.filter(pk=prod.pk).update(stock=F("stock") - qty)
                prod.stock -= qty  # локально тоже уменьшим

                order_items.append(
                    OrderItem(order=order, product=prod, quantity=qty, price_at_purchase=prod.price)
                )
            OrderItem.objects.bulk_create(order_items)

            # пересчёт total
            order.recalc_total(save=True)

        # Celery: PDF + имитация email
        tasks.order_created_generate_pdf_and_email.delay(order.id)
        return order


# ---------- ЧТЕНИЕ ЗАКАЗОВ ----------

class OrderListSerializer(serializers.ModelSerializer):
    """Список заказов (кратко)."""
    items_count = serializers.IntegerField(source="items.count", read_only=True)

    class Meta:
        model = Order
        fields = ("id", "status", "total_price", "created_at", "updated_at", "items_count")
        read_only_fields = fields


class OrderDetailSerializer(serializers.ModelSerializer):
    """Детали заказа со списком позиций."""
    items = OrderItemReadSerializer(many=True, read_only=True)

    class Meta:
        model = Order
        fields = ("id", "user", "status", "total_price", "created_at", "updated_at", "items")
        read_only_fields = fields


# ---------- PATCH СТАТУСА ----------

class OrderStatusPatchSerializer(serializers.ModelSerializer):
    """
    Обновление статуса (PATCH).
    Переходы валидируются на уровне модели (clean()).
    """

    class Meta:
        model = Order
        fields = ("status",)

    def update(self, instance: Order, validated_data):
        instance.status = validated_data["status"]
        try:
            instance.full_clean()  # дергает Order.clean() с валидацией перехода
        except DjangoValidationError as e:
            # конвертируем в DRF-валидатор → HTTP 400
            raise serializers.ValidationError(e.message_dict or {"detail": e.messages})

        instance.save(update_fields=["status", "updated_at"])
        if instance.status == Order.STATUS_SHIPPED:
            tasks.order_shipped_notify_external.delay(instance.id)
        return instance

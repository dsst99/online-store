# apps/orders/admin.py
from django import forms
from django.contrib import admin, messages
from django.core.exceptions import ValidationError
from django.db.models import Count
from django.utils.html import format_html

from .models import Order, OrderItem


# --- Inline form: блокируем правку price_at_purchase на существующих строках ---
class OrderItemInlineForm(forms.ModelForm):
    class Meta:
        model = OrderItem
        fields = ("product", "quantity", "price_at_purchase")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # разрешаем указать цену при добавлении, но блокируем при редактировании
        if self.instance and self.instance.pk:
            self.fields["price_at_purchase"].disabled = True


class OrderItemInline(admin.TabularInline):
    model = OrderItem
    form = OrderItemInlineForm
    extra = 0
    # Надёжный выбор через лупу (без select2)
    raw_id_fields = ("product",)
    fields = ("product", "quantity", "price_at_purchase", "created_at")
    readonly_fields = ("created_at",)

    # Разрешённый набор продуктов: только активные и с остатком
    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "product":
            from apps.catalog.models import Product  # локальный импорт, чтобы избежать циклов
            qs = kwargs.get("queryset") or Product.objects.all()
            kwargs["queryset"] = qs.filter(is_active=True, stock__gt=0)
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

    def has_add_permission(self, request, obj=None):
        return False if (obj and obj.is_readonly) else super().has_add_permission(request, obj)

    def has_change_permission(self, request, obj=None):
        return False if (obj and obj.is_readonly) else super().has_change_permission(request, obj)

    def has_delete_permission(self, request, obj=None):
        return False if (obj and obj.is_readonly) else super().has_delete_permission(request, obj)


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    # Красивый цветной статус в списке
    @admin.display(description="Статус")
    def colored_status(self, obj):
        colors = {
            Order.STATUS_PENDING: "#888",
            Order.STATUS_PROCESSING: "#0a7",
            Order.STATUS_SHIPPED: "#06c",
            Order.STATUS_DELIVERED: "#3a3",
            Order.STATUS_CANCELLED: "#c33",
        }
        c = colors.get(obj.status, "#555")
        return format_html('<b style="color:{}">{}</b>', c, obj.get_status_display())

    list_display = ("id", "user", "colored_status", "items_count", "total_price", "created_at")
    list_filter = ("status", "created_at")
    date_hierarchy = "created_at"
    search_fields = ("id", "user__username", "user__email")
    # Надёжный выбор пользователя через лупу
    raw_id_fields = ("user",)
    inlines = [OrderItemInline]
    # Состав управляем только через инлайн
    exclude = ("products",)
    actions = ("mark_processing", "mark_shipped", "mark_delivered", "mark_cancelled", "recalc_totals")
    list_per_page = 50
    save_on_top = True
    actions_on_top = True
    actions_on_bottom = True
    ordering = ("-created_at", "id")

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        return qs.select_related("user").annotate(_items_count=Count("items"))

    @admin.display(ordering="_items_count", description="Позиций")
    def items_count(self, obj):
        return getattr(obj, "_items_count", 0)

    # Разрешённый набор пользователей: только активные
    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "user":
            qs = kwargs.get("queryset") or self.model._meta.get_field("user").remote_field.model.objects.all()
            kwargs["queryset"] = qs.filter(is_active=True)
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

    def get_readonly_fields(self, request, obj=None):
        base_ro = {"total_price", "created_at", "updated_at"}
        if obj and obj.is_readonly:
            return tuple(sorted({f.name for f in obj._meta.fields} | base_ro))
        return tuple(sorted(base_ro))

    def has_delete_permission(self, request, obj=None):
        return False if (obj and obj.is_readonly) else super().has_delete_permission(request, obj)

    # Скрываем экшены смены статуса, если выбран финальный статус в фильтре (кастомный UX-штрих)
    def get_actions(self, request):
        actions = super().get_actions(request)
        status_filter = request.GET.get("status__exact")
        if status_filter in {Order.STATUS_SHIPPED, Order.STATUS_DELIVERED, Order.STATUS_CANCELLED}:
            for a in ("mark_processing", "mark_shipped", "mark_delivered", "mark_cancelled"):
                actions.pop(a, None)
        return actions

    # --- массовая смена статуса с проверкой переходов через clean() ---
    def _bulk_set_status(self, request, queryset, new_status, label):
        ok = fail = 0
        for order in queryset:
            old = order.status
            order.status = new_status
            try:
                order.full_clean()  # проверяет валидный переход и инварианты
                order.save(update_fields=["status", "updated_at"])
                ok += 1
            except ValidationError as e:
                fail += 1
                self.message_user(
                    request,
                    f"Заказ #{order.pk}: запрещён переход {old} → {new_status}. {e}",
                    level=messages.WARNING,
                )
        if ok:
            self.message_user(request, f"{label}: успешно — {ok}", level=messages.SUCCESS)
        if fail:
            self.message_user(request, f"{label}: отклонено — {fail}", level=messages.WARNING)

    def mark_processing(self, request, queryset):
        self._bulk_set_status(request, queryset, Order.STATUS_PROCESSING, "Переведено в Processing")

    mark_processing.short_description = "Перевести в Processing"

    def mark_shipped(self, request, queryset):
        self._bulk_set_status(request, queryset, Order.STATUS_SHIPPED, "Отмечено как Shipped")

    mark_shipped.short_description = "Отметить как Shipped"

    def mark_delivered(self, request, queryset):
        self._bulk_set_status(request, queryset, Order.STATUS_DELIVERED, "Отмечено как Delivered")

    mark_delivered.short_description = "Отметить как Delivered"

    def mark_cancelled(self, request, queryset):
        self._bulk_set_status(request, queryset, Order.STATUS_CANCELLED, "Отменить")

    mark_cancelled.short_description = "Отменить заказы"

    # --- пересчёт total (на случай рассинхронизаций) ---
    def recalc_totals(self, request, queryset):
        for order in queryset:
            order.recalc_total(save=True)
        self.message_user(request, f"Пересчитано заказов: {queryset.count()}", level=messages.SUCCESS)

    recalc_totals.short_description = "Пересчитать итоги (total_price)"

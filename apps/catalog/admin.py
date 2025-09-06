# apps/catalog/admin.py
from django.contrib import admin
from .models import Category, Product


# --- общие экшены -------------------------------------------------------------
@admin.action(description="Мягко удалить (is_active=False)")
def soft_delete(modeladmin, request, queryset):
    for obj in queryset:
        # используем метод модели (он обновляет updated_at)
        if hasattr(obj, "soft_delete"):
            obj.soft_delete()


@admin.action(description="Восстановить (is_active=True)")
def restore(modeladmin, request, queryset):
    queryset.update(is_active=True)


# --- Category -----------------------------------------------------------------
@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "slug", "is_active", "created_at", "updated_at")
    list_filter = ("is_active", "created_at", "updated_at")
    search_fields = ("name", "slug")
    ordering = ("name",)
    readonly_fields = ("created_at", "updated_at")
    prepopulated_fields = {"slug": ("name",)}
    actions = (soft_delete, restore)


# --- Product ------------------------------------------------------------------
@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "category", "price", "stock", "is_active", "created_at", "updated_at")
    list_filter = ("is_active", "category", "created_at")
    search_fields = ("name", "category__name", "category__slug")
    ordering = ("name",)
    readonly_fields = ("created_at", "updated_at")
    list_select_related = ("category",)
    autocomplete_fields = ("category",)
    actions = (soft_delete, restore)

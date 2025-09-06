from django.utils.text import slugify
from rest_framework import serializers

from apps.catalog.models import Category, Product


class CategoryListSerializer(serializers.ModelSerializer):
    """Сериализатор списка категорий для публичного API (id, name, slug, created_at, updated_at)."""

    class Meta:
        model = Category
        fields = ['id', 'name', 'slug', 'created_at', 'updated_at']
        read_only_fields = ['id', 'created_at', 'updated_at']


class CategoryDetailSerializer(serializers.ModelSerializer):
    """Сериализатор деталей категории для публичного API (id, name, slug, created_at, updated_at)."""

    class Meta:
        model = Category
        fields = ['id', 'name', 'slug', 'is_active', 'created_at', 'updated_at']
        read_only_fields = ['id', 'created_at', 'updated_at']


def validate_name(self, value):
    trimmed = value.strip()
    if not trimmed:
        raise serializers.ValidationError('Имя не может быть пустым')
    return trimmed


def validate_slug(self, value):
    """
    Нормализация slug:
    - если slug передан → slugify + обрезка до 100
    - если не передан → генерируем из name (из входных данных или из instance)
    - проверяем непустоту после нормализации
    """
    if value:
        new_slug = slugify(value)
    else:
        name = (self.initial_data.get('name') if isinstance(self.initial_data, dict) else None) \
               or getattr(self.instance, 'name', '')
        new_slug = slugify(name or '')
    new_slug = (new_slug or '')[:100]
    if not new_slug:
        raise serializers.ValidationError('Slug не может быть пустым')
    return new_slug


class CategoryInlineSerializer(serializers.ModelSerializer):
    """Короткое представление категории внутри продукта (public)."""

    class Meta:
        model = Category
        fields = ['id', 'name', 'slug']
        read_only_fields = ['id', 'name', 'slug']


class ProductListSerializer(serializers.ModelSerializer):
    """Сериализатор списка продуктов для публичного API (id, name, price, имя категории)."""
    category = serializers.CharField(source='category.name', read_only=True)

    class Meta:
        model = Product
        fields = ['id', 'name', 'price', 'category']
        read_only_fields = ['id']


class ProductDetailSerializer(serializers.ModelSerializer):
    """
    Детали продукта для публичного API.
    Публичный контракт: без is_active (неактивные продукты не выдаём, см. вью).
    """
    category = CategoryInlineSerializer(read_only=True)

    class Meta:
        model = Product
        fields = [
            'id',
            'name',
            'description',
            'price',
            'stock',
            'category',
            'created_at',
            'updated_at',
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']

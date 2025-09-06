from django.core.exceptions import ValidationError
from django.db import models
from django.db.models.functions import Lower
from django.utils.text import slugify


class Category(models.Model):
    """Модель для категорий товаров"""
    name = models.CharField(max_length=100, unique=True, help_text='Название категории')
    slug = models.SlugField(
        max_length=100,
        db_index=True,
        unique=True,
        verbose_name='Slug',
        help_text="Уникальный идентификатор категории в URL",
    )
    is_active = models.BooleanField(default=True, db_index=True, help_text='Активно')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='Создано')
    updated_at = models.DateTimeField(auto_now=True, help_text='Обновлено')

    def save(self, *args, **kwargs):
        """
        Нормализация name/slug.
        - если slug пуст, генерируем из name; иначе нормализуем перед сохранением.
        - trim для name; защита от пустого slug после slugify.
        """
        if self.name:
            self.name = self.name.strip()

        base_slug = self.slug.strip() if self.slug else ""
        if not base_slug and self.name:
            base_slug = self.name

        self.slug = slugify(base_slug)[:100]
        if not self.slug:
            raise ValidationError('Slug не может быть пустым после нормализации')

        super().save(*args, **kwargs)

    def soft_delete(self):
        """Мягкое удаление (is_active = False)."""
        if self.is_active:
            self.is_active = False
            self.save(update_fields=['is_active', 'updated_at'])

    class Meta:
        """Индексы под сортировку/поиск по времени и имени"""
        indexes = [
            models.Index(fields=['created_at']),
            models.Index(fields=['updated_at']),
            models.Index(Lower('name'), name='category_name_lower_idx'),
        ]
        ordering = ['name']
        verbose_name = 'Категория'
        verbose_name_plural = 'Категории'

    def __str__(self):
        return self.name


class Product(models.Model):
    """Модель для продуктов"""
    name = models.CharField(max_length=150, verbose_name='Название продукта')
    description = models.TextField()
    price = models.DecimalField(max_digits=8, decimal_places=2, help_text='Цена')
    stock = models.PositiveIntegerField(default=0, verbose_name='На складе')
    category = models.ForeignKey(
        Category,
        on_delete=models.PROTECT,
        db_index=True,
        related_name='products',
        verbose_name='Категория',
    )
    is_active = models.BooleanField(default=True, db_index=True, verbose_name='Активно')
    created_at = models.DateTimeField(auto_now_add=True, db_index=True, verbose_name='Создано')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='Обновлено')

    def save(self, *args, **kwargs):
        if self.name:
            self.name = self.name.strip()
        super().save(*args, **kwargs)

    def soft_delete(self):
        """Мягкое удаление продукта (is_active = False)."""
        if self.is_active:
            self.is_active = False
            self.save(update_fields=['is_active', 'updated_at'])

    class Meta:
        """Проверка значений и индексы под выборки и поиск"""
        indexes = [
            models.Index(fields=['price']),
            models.Index(fields=['category', 'is_active', '-created_at']),
            models.Index(Lower('name'), name='product_name_lower_idx'),
        ]
        constraints = [
            models.CheckConstraint(condition=models.Q(price__gte=0), name="price_gte_0"),
            models.CheckConstraint(condition=models.Q(stock__gte=0), name="stock_gte_0"),
        ]
        ordering = ['name']
        verbose_name = "Продукт"
        verbose_name_plural = 'Продукты'

    def __str__(self):
        return self.name

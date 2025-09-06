from django.urls import path
from .views import (
    CategoryListView,
    CategoryView,
    ProductListView,
    ProductDetailView,
)

urlpatterns = [
    # Категории
    path("categories/", CategoryListView.as_view(), name="categories-list"),
    path("categories/<int:pk>/", CategoryView.as_view(), name="categories-detail"),

    # Продукты
    path("products/", ProductListView.as_view(), name="products-list"),
    path("products/<int:pk>/", ProductDetailView.as_view(), name="products-detail"),
]

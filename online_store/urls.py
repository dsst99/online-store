from django.contrib import admin
from django.urls import path, include
from drf_spectacular.views import (SpectacularAPIView,
                                   SpectacularSwaggerView,
                                   SpectacularRedocView)

urlpatterns = [
    path('admin/', admin.site.urls),
    # схема OpenAPI
    path('api/schema/', SpectacularAPIView.as_view(), name='schema'),
    # документация Swagger UI
    path('api/schema/swagger-ui/', SpectacularSwaggerView.as_view(url_name='schema'), name='swagger-ui'),
    # документация Redoc
    path('api/schema/redoc/', SpectacularRedocView.as_view(url_name='schema'), name='redoc'),

    # бизнес-эндпоинты
    path('api/v1/', include('apps.catalog.urls')),
    path('api/v1/', include('apps.orders.urls')),
    path('api/v1/', include('apps.users.urls')),
]

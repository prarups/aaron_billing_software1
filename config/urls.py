from django.contrib import admin
from django.urls import path, include
from django.shortcuts import redirect
from core import views as core_views

urlpatterns = [
    path('admin/', admin.site.urls),
    path('users/', include('users.urls')),
    path('core/', include('core.urls')),
    path('billing/', include('billing.urls')),
    path('pos/', core_views.pos_view, name='pos_view'),
    path('', lambda r: redirect('dashboard' if r.user.is_authenticated else 'login')),
]

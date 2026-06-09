from django.contrib import admin
from django.urls import path, include
from django.shortcuts import redirect
from django.views.generic import TemplateView
from core import views as core_views

urlpatterns = [
    path('admin/', admin.site.urls),
    path('service-worker.js', TemplateView.as_view(template_name="service-worker.js", content_type='application/javascript'), name='service_worker'),
    path('users/', include('users.urls')),
    path('core/', include('core.urls')),
    path('billing/', include('billing.urls')),
    path('pos/', core_views.pos_view, name='pos_view'),
    path('', lambda r: redirect('dashboard' if r.user.is_authenticated else 'login')),
]

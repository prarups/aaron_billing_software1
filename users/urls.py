from django.urls import path
from django.contrib.auth import views as auth_views
from . import views
from .forms import CustomAuthenticationForm

urlpatterns = [
    path('login/', auth_views.LoginView.as_view(template_name='registration/login.html', authentication_form=CustomAuthenticationForm), name='login'),
    path('logout/', auth_views.LogoutView.as_view(), name='logout'),
    path('dashboard/redirect/', views.dashboard_redirect, name='dashboard_redirect'),
    path('dashboard/owner/', views.OwnerDashboardView.as_view(), name='owner_dashboard'),
    path('dashboard/owner/export-csv/', views.export_dashboard_sales_csv, name='export_dashboard_sales_csv'),
    path('dashboard/manager/', views.ManagerDashboardView.as_view(), name='manager_dashboard'),
    path('dashboard/staff/', views.StaffDashboardView.as_view(), name='staff_dashboard'),
    # Alias
    path('dashboard/', views.dashboard_redirect, name='dashboard'),
    path('switch-branch/', views.switch_branch, name='switch_branch'),

    # Branch Management URLs
    path('branch/add/', views.branch_create, name='branch_create'),
    path('branch/edit/<int:pk>/', views.branch_edit, name='branch_edit'),
    path('branch/delete/<int:pk>/', views.branch_delete, name='branch_delete'),

    # Staff Management URLs
    path('staff/add/', views.staff_create, name='staff_create'),
    path('staff/edit/<int:pk>/', views.staff_edit, name='staff_edit'),
    path('staff/delete/<int:pk>/', views.staff_delete, name='staff_delete'),
    path('staff/toggle/<int:staff_id>/', views.toggle_staff_active, name='staff_toggle'),
    path('staff/toggle-product-rights/<int:staff_id>/', views.toggle_product_rights, name='toggle_product_rights'),
]


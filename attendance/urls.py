from django.urls import path
from . import views

app_name = 'attendance'

urlpatterns = [
    path('dashboard/', views.attendance_dashboard, name='dashboard'),
    path('check-in/', views.check_in, name='check_in'),
    path('mid-day/', views.mid_day_check, name='mid_day'),
    path('check-out/', views.check_out, name='check_out'),
    
    path('leaves/', views.leave_list, name='leave_list'),
    path('leaves/request/', views.leave_request, name='leave_request'),
    path('leaves/approve/<int:pk>/<str:action>/', views.leave_approve, name='leave_approve'),
    
    path('permissions/', views.permission_list, name='permission_list'),
    path('permissions/request/', views.permission_request, name='permission_request'),
    path('permissions/approve/<int:pk>/<str:action>/', views.permission_approve, name='permission_approve'),
    
    path('reports/', views.attendance_reports, name='reports'),
    path('my-summary/', views.my_summary_view, name='my_summary'),
    path('management-overview/', views.management_overview_view, name='management_overview'),
    
    path('salaries/', views.salary_list, name='payroll_list'),
    path('salaries/config/<int:user_id>/', views.salary_config_view, name='salary_config'),
    path('salaries/payroll/generate/', views.generate_payroll, name='generate_payroll'),
    path('salaries/payroll/pay/<int:payroll_id>/', views.mark_payroll_paid, name='mark_payroll_paid'),
    path('edit-ajax/<int:pk>/', views.edit_attendance_ajax, name='edit_attendance_ajax'),
]

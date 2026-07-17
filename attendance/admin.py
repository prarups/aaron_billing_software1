from django.contrib import admin
from .models import Attendance, LeaveRequest, PermissionRequest, SalaryConfig, MonthlyPayroll

@admin.register(Attendance)
class AttendanceAdmin(admin.ModelAdmin):
    list_display = ('user', 'branch', 'date', 'status', 'check_in', 'check_out', 'mid_day_time')
    list_filter = ('status', 'branch', 'date')
    search_fields = ('user__username', 'user__employee_id')
    readonly_fields = ('check_in', 'check_out', 'mid_day_time')

@admin.register(LeaveRequest)
class LeaveRequestAdmin(admin.ModelAdmin):
    list_display = ('user', 'leave_type', 'start_date', 'end_date', 'status', 'approved_by')
    list_filter = ('status', 'leave_type')
    search_fields = ('user__username', 'reason')

@admin.register(PermissionRequest)
class PermissionRequestAdmin(admin.ModelAdmin):
    list_display = ('user', 'date', 'start_time', 'end_time', 'status', 'approved_by')
    list_filter = ('status', 'date')
    search_fields = ('user__username', 'reason')

@admin.register(SalaryConfig)
class SalaryConfigAdmin(admin.ModelAdmin):
    list_display = ('user', 'monthly_base_salary', 'late_deduction_amount', 'lop_deduction_amount', 'max_permissions_per_month', 'max_hours_per_permission')
    search_fields = ('user__username',)

@admin.register(MonthlyPayroll)
class MonthlyPayrollAdmin(admin.ModelAdmin):
    list_display = ('user', 'month', 'year', 'base_salary', 'deductions', 'net_salary', 'status')
    list_filter = ('status', 'year', 'month')
    search_fields = ('user__username',)

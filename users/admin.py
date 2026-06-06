from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import User

@admin.register(User)
class CustomUserAdmin(UserAdmin):
    list_display = ('username', 'email', 'role', 'employee_id', 'active_branch', 'is_staff')
    fieldsets = UserAdmin.fieldsets + (
        ('Role & Branch & Employee ID', {'fields': ('role', 'branches', 'active_branch', 'employee_id')}),
    )
    add_fieldsets = UserAdmin.add_fieldsets + (
        ('Role & Branch & Employee ID', {'fields': ('role', 'branches', 'active_branch', 'employee_id')}),
    )


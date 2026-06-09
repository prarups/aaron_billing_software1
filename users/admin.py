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

    def has_view_permission(self, request, obj=None):
        return request.user.is_superuser or getattr(request.user, 'role', '') == 'owner'

    def has_add_permission(self, request):
        return request.user.is_superuser or getattr(request.user, 'role', '') == 'owner'

    def has_change_permission(self, request, obj=None):
        return request.user.is_superuser or getattr(request.user, 'role', '') == 'owner'

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser or getattr(request.user, 'role', '') == 'owner'


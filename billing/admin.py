from django.contrib import admin
import csv
from django.http import HttpResponse
from .models import Bill, BillItem

class BillItemInline(admin.TabularInline):
    model = BillItem
    extra = 0

@admin.register(Bill)
class BillAdmin(admin.ModelAdmin):
    list_display = ('id', 'invoice_number', 'branch', 'staff', 'total_amount', 'payment_method', 'created_at')
    list_filter = ('branch', 'staff', 'payment_method', 'created_at')
    search_fields = ('id', 'invoice_number', 'customer_name', 'customer_phone')
    readonly_fields = ('sequence_number', 'invoice_number', 'share_id')
    inlines = [BillItemInline]
    actions = ['export_as_csv']

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        if request.user.is_superuser or getattr(request.user, 'role', '') == 'owner':
            return qs
        return qs.filter(branch=request.user.active_branch)

    def has_view_permission(self, request, obj=None):
        return request.user.is_superuser or getattr(request.user, 'role', '') in ['owner', 'manager']

    @admin.action(description="Export Selected to CSV")
    def export_as_csv(self, request, queryset):
        meta = self.model._meta
        field_names = [field.name for field in meta.fields]

        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = 'attachment; filename={}.csv'.format(meta)
        writer = csv.writer(response)

        writer.writerow(field_names)
        for obj in queryset:
            row = writer.writerow([getattr(obj, field) for field in field_names])

        return response

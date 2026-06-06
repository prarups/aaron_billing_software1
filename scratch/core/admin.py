from django.contrib import admin
from django.db.models import Q
from .models import Branch, Product, ProductRegistry, StockTransaction, StockAdjustment, ComboPrice

@admin.register(Branch)
class BranchAdmin(admin.ModelAdmin):
    list_display = ('name', 'location', 'contact_number', 'code', 'created_at')
    readonly_fields = ('code',)
    search_fields = ('name', 'location')

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        if request.user.is_superuser:
            return qs
        return qs.filter(id=request.user.active_branch_id)

    def has_add_permission(self, request):
        return request.user.is_superuser or getattr(request.user, 'role', '') in ['owner', 'manager']

    def has_change_permission(self, request, obj=None):
        return request.user.is_superuser or getattr(request.user, 'role', '') in ['owner', 'manager']

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser or getattr(request.user, 'role', '') in ['owner', 'manager']


class ProductRegistryInline(admin.TabularInline):
    model = ProductRegistry
    extra = 1

class ComboPriceInline(admin.TabularInline):
    model = ComboPrice
    extra = 0




@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ('name', 'barcode', 'price', 'size', 'created_at')
    list_filter = ('created_at',)
    search_fields = ('name', 'barcode')
    inlines = [ProductRegistryInline, ComboPriceInline]

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        if request.user.is_superuser:
            return qs
        # Show products registered to their active branch, or products with no registrations yet
        return qs.filter(
            Q(productregistry__branch_id=request.user.active_branch_id) |
            Q(productregistry__isnull=True)
        ).distinct()


@admin.register(ProductRegistry)
class ProductRegistryAdmin(admin.ModelAdmin):
    list_display = ('product', 'branch', 'stock_quantity', 'damaged_qty', 'updated_at')
    list_filter = ('branch', 'updated_at')
    search_fields = ('product__name', 'product__barcode', 'branch__name')

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        if request.user.is_superuser:
            return qs
        return qs.filter(branch_id=request.user.active_branch_id)

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "branch" and not request.user.is_superuser:
            kwargs["queryset"] = Branch.objects.filter(id=request.user.active_branch_id)
        return super().formfield_for_foreignkey(db_field, request, **kwargs)


@admin.register(StockTransaction)
class StockTransactionAdmin(admin.ModelAdmin):
    list_display = ('product', 'branch', 'transaction_type', 'quantity', 'reference', 'user', 'created_at')
    list_filter = ('branch', 'transaction_type', 'created_at')
    search_fields = ('product__name', 'product__barcode', 'reference')
    readonly_fields = ('created_at',)

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        if request.user.is_superuser:
            return qs
        return qs.filter(branch_id=request.user.active_branch_id)


@admin.register(StockAdjustment)
class StockAdjustmentAdmin(admin.ModelAdmin):
    list_display = ('product', 'branch', 'opening_balance', 'correction_amount', 'closing_stock', 'user', 'created_at')
    list_filter = ('branch', 'created_at')
    search_fields = ('product__name', 'product__barcode', 'reason')
    readonly_fields = ('created_at',)

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        if request.user.is_superuser:
            return qs
        return qs.filter(branch_id=request.user.active_branch_id)


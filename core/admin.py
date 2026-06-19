from django.contrib import admin
from django.db.models import Q
from .models import Branch, Product, ProductRegistry, StockTransaction, StockAdjustment, ComboPrice, ComboGroup, ComboTier

@admin.register(Branch)
class BranchAdmin(admin.ModelAdmin):
    list_display = ('name', 'location', 'contact_number', 'code', 'created_at')
    readonly_fields = ('code',)
    search_fields = ('name', 'location')

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        if request.user.is_superuser or getattr(request.user, 'role', '') == 'owner':
            return qs
        accessible_branches = request.user.get_accessible_branches()
        return qs.filter(id__in=accessible_branches)

    def has_view_permission(self, request, obj=None):
        return request.user.is_superuser or getattr(request.user, 'role', '') in ['owner', 'manager', 'assistant_manager']

    def has_add_permission(self, request):
        return request.user.is_superuser or getattr(request.user, 'role', '') in ['owner', 'manager', 'assistant_manager']

    def has_change_permission(self, request, obj=None):
        return request.user.is_superuser or getattr(request.user, 'role', '') in ['owner', 'manager', 'assistant_manager']

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser or getattr(request.user, 'role', '') in ['owner', 'manager', 'assistant_manager']


class ProductRegistryInline(admin.TabularInline):
    model = ProductRegistry
    extra = 1

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "branch" and not (request.user.is_superuser or getattr(request.user, 'role', '') == 'owner'):
            kwargs["queryset"] = request.user.get_accessible_branches()
        return super().formfield_for_foreignkey(db_field, request, **kwargs)


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
        if request.user.is_superuser or getattr(request.user, 'role', '') == 'owner':
            return qs
        accessible_branches = request.user.get_accessible_branches()
        return qs.filter(
            Q(productregistry__branch__in=accessible_branches) |
            Q(productregistry__isnull=True)
        ).distinct()

    def has_view_permission(self, request, obj=None):
        return request.user.is_superuser or getattr(request.user, 'role', '') in ['owner', 'manager', 'assistant_manager']

    def has_add_permission(self, request):
        return request.user.is_superuser or getattr(request.user, 'role', '') == 'owner' or (
            getattr(request.user, 'role', '') in ['manager', 'assistant_manager'] and getattr(request.user, 'has_product_rights', False)
        )

    def has_change_permission(self, request, obj=None):
        return request.user.is_superuser or getattr(request.user, 'role', '') == 'owner' or (
            getattr(request.user, 'role', '') in ['manager', 'assistant_manager'] and getattr(request.user, 'has_product_rights', False)
        )

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser or getattr(request.user, 'role', '') == 'owner' or (
            getattr(request.user, 'role', '') in ['manager', 'assistant_manager'] and getattr(request.user, 'has_product_rights', False)
        )


@admin.register(ProductRegistry)
class ProductRegistryAdmin(admin.ModelAdmin):
    list_display = ('product', 'branch', 'stock_quantity', 'damaged_qty', 'updated_at')
    list_filter = ('branch', 'updated_at')
    search_fields = ('product__name', 'product__barcode', 'branch__name')

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        if request.user.is_superuser or getattr(request.user, 'role', '') == 'owner':
            return qs
        accessible_branches = request.user.get_accessible_branches()
        return qs.filter(branch__in=accessible_branches)

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "branch" and not (request.user.is_superuser or getattr(request.user, 'role', '') == 'owner'):
            kwargs["queryset"] = request.user.get_accessible_branches()
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

    def has_view_permission(self, request, obj=None):
        return request.user.is_superuser or getattr(request.user, 'role', '') in ['owner', 'manager']

    def has_add_permission(self, request):
        return request.user.is_superuser or getattr(request.user, 'role', '') in ['owner', 'manager']

    def has_change_permission(self, request, obj=None):
        return request.user.is_superuser or getattr(request.user, 'role', '') in ['owner', 'manager']

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser or getattr(request.user, 'role', '') in ['owner', 'manager']


@admin.register(StockTransaction)
class StockTransactionAdmin(admin.ModelAdmin):
    list_display = ('product', 'branch', 'transaction_type', 'quantity', 'reference', 'user', 'created_at')
    list_filter = ('branch', 'transaction_type', 'created_at')
    search_fields = ('product__name', 'product__barcode', 'reference')
    readonly_fields = ('created_at',)

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        if request.user.is_superuser or getattr(request.user, 'role', '') == 'owner':
            return qs
        accessible_branches = request.user.get_accessible_branches()
        return qs.filter(branch__in=accessible_branches)

    def has_view_permission(self, request, obj=None):
        return request.user.is_superuser or getattr(request.user, 'role', '') in ['owner', 'manager']

    def has_add_permission(self, request):
        return request.user.is_superuser or getattr(request.user, 'role', '') in ['owner', 'manager']

    def has_change_permission(self, request, obj=None):
        return request.user.is_superuser or getattr(request.user, 'role', '') in ['owner', 'manager']

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser or getattr(request.user, 'role', '') in ['owner', 'manager']


@admin.register(StockAdjustment)
class StockAdjustmentAdmin(admin.ModelAdmin):
    list_display = ('product', 'branch', 'opening_balance', 'correction_amount', 'closing_stock', 'user', 'created_at')
    list_filter = ('branch', 'created_at')
    search_fields = ('product__name', 'product__barcode', 'reason')
    readonly_fields = ('created_at',)

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        if request.user.is_superuser or getattr(request.user, 'role', '') == 'owner':
            return qs
        accessible_branches = request.user.get_accessible_branches()
        return qs.filter(branch__in=accessible_branches)

    def has_view_permission(self, request, obj=None):
        return request.user.is_superuser or getattr(request.user, 'role', '') in ['owner', 'manager']

    def has_add_permission(self, request):
        return request.user.is_superuser or getattr(request.user, 'role', '') in ['owner', 'manager']

    def has_change_permission(self, request, obj=None):
        return request.user.is_superuser or getattr(request.user, 'role', '') in ['owner', 'manager']

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser or getattr(request.user, 'role', '') in ['owner', 'manager']


class ComboTierInline(admin.TabularInline):
    model = ComboTier
    extra = 0


@admin.register(ComboGroup)
class ComboGroupAdmin(admin.ModelAdmin):
    list_display = ('name', 'is_active', 'created_at')
    list_filter = ('is_active',)
    search_fields = ('name',)
    filter_horizontal = ('branches', 'products')
    inlines = [ComboTierInline]

from django.contrib import admin
from django.db.models import Q
from django.utils.html import format_html
from django.urls import reverse
from .models import Branch, Product, ProductRegistry, StockTransaction, StockAdjustment, ComboPrice, ComboGroup, ComboTier

class ProductRegistryBranchInline(admin.TabularInline):
    model = ProductRegistry
    extra = 0
    raw_id_fields = ('product',)
    fields = ('product', 'stock_quantity', 'damaged_qty', 'low_stock_threshold')
    verbose_name = "Branch Product Stock"
    verbose_name_plural = "Branch Product Stocks"

@admin.register(Branch)
class BranchAdmin(admin.ModelAdmin):
    list_display = ('name', 'location', 'contact_number', 'code', 'view_products_link', 'created_at')
    readonly_fields = ('code',)
    search_fields = ('name', 'location')
    inlines = [ProductRegistryBranchInline]

    def view_products_link(self, obj):
        url = reverse('admin:core_productregistry_changelist') + f"?branch__id__exact={obj.id}"
        return format_html('<a class="button" style="background-color: #4f46e5; color: white; padding: 4px 10px; border-radius: 4px; text-decoration: none; font-weight: bold; font-size: 11px;" href="{}">View Products</a>', url)
    view_products_link.short_description = "Branch Products"

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
    list_display = ('name', 'barcode', 'price', 'size', 'display_branches', 'created_at')
    list_filter = ('branches', 'created_at')
    search_fields = ('name', 'barcode')
    inlines = [ProductRegistryInline, ComboPriceInline]

    def display_branches(self, obj):
        return ", ".join([b.name for b in obj.branches.all()])
    display_branches.short_description = "Branches"

    def get_queryset(self, request):
        qs = super().get_queryset(request).prefetch_related('branches')
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
    list_display = (
        'get_product_name', 
        'get_barcode', 
        'get_price', 
        'get_size', 
        'branch', 
        'stock_quantity', 
        'damaged_qty', 
        'low_stock_threshold', 
        'updated_at'
    )
    list_display_links = ('get_product_name',)
    list_filter = ('branch', 'product__created_at')
    search_fields = ('product__name', 'product__barcode', 'branch__name')
    list_editable = ('stock_quantity', 'damaged_qty', 'low_stock_threshold')

    def get_product_name(self, obj):
        return obj.product.name
    get_product_name.short_description = 'Product Name'
    get_product_name.admin_order_field = 'product__name'

    def get_barcode(self, obj):
        return obj.product.barcode
    get_barcode.short_description = 'Barcode'
    get_barcode.admin_order_field = 'product__barcode'

    def get_price(self, obj):
        return f"₹{obj.product.price:.0f}"
    get_price.short_description = 'Price'
    get_price.admin_order_field = 'product__price'

    def get_size(self, obj):
        return obj.product.size or "—"
    get_size.short_description = 'Size'
    get_size.admin_order_field = 'product__size'

    def get_queryset(self, request):
        qs = super().get_queryset(request).select_related('product', 'branch')
        if request.user.is_superuser or getattr(request.user, 'role', '') == 'owner':
            return qs
        accessible_branches = request.user.get_accessible_branches()
        return qs.filter(branch__in=accessible_branches)

    def changelist_view(self, request, extra_context=None):
        if 'branch__id__exact' not in request.GET and not request.GET.get('q') and request.method == 'GET':
            from django.shortcuts import render
            branches = Branch.objects.all()
            if not request.user.is_superuser and getattr(request.user, 'role', '') != 'owner':
                accessible = request.user.get_accessible_branches()
                branches = branches.filter(id__in=accessible)
            
            extra_context = extra_context or {}
            extra_context['branches_list'] = branches
            extra_context['title'] = "Select a Branch to View Products"
            return render(request, 'admin/core/productregistry/select_branch.html', extra_context)
            
        return super().changelist_view(request, extra_context=extra_context)

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
    list_display = ('combo_id', 'name', 'display_branches', 'is_active', 'created_at')
    list_filter = ('branches', 'is_active')
    search_fields = ('name', 'combo_id')
    filter_horizontal = ('branches', 'products')
    inlines = [ComboTierInline]

    def display_branches(self, obj):
        return ", ".join([b.name for b in obj.branches.all()])
    display_branches.short_description = "Branches"

    def get_queryset(self, request):
        return super().get_queryset(request).prefetch_related('branches')

from django.db import models
from django import forms

class Branch(models.Model):
    name = models.CharField(max_length=100)
    location = models.CharField(max_length=255)
    contact_number = models.CharField(max_length=20, blank=True)
    invoice_prefix = models.CharField(max_length=10, default='AG', unique=True, help_text="Prefix for invoice numbers (e.g., 'AG')")
    code = models.PositiveIntegerField(unique=True, editable=False, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Adminpage"
        verbose_name_plural = "Adminpage"

    def save(self, *args, **kwargs):
        if not self.code:
            from django.db.models import Max
            max_code = Branch.objects.aggregate(max_code=Max('code'))['max_code']
            self.code = (max_code + 1) if max_code else 10001
            
        # Ensure invoice_prefix is unique
        if not self.invoice_prefix or self.invoice_prefix == 'AG':
            existing_prefixes = Branch.objects.exclude(pk=self.pk).values_list('invoice_prefix', flat=True)
            if self.invoice_prefix in existing_prefixes:
                counter = 2
                new_prefix = f"AG{counter}"
                while new_prefix in existing_prefixes:
                    counter += 1
                    new_prefix = f"AG{counter}"
                self.invoice_prefix = new_prefix
                
        super().save(*args, **kwargs)

    def __str__(self):
        if self.code:
            return f"{self.name} ({self.code})"
        return self.name


class Product(models.Model):
    branch = models.ForeignKey(Branch, on_delete=models.CASCADE, related_name='branch_products', null=True, blank=True)
    name = models.CharField(max_length=200, blank=True, default='')
    barcode = models.CharField(max_length=50, db_index=True)
    price = models.DecimalField(max_digits=10, decimal_places=0)

    size = models.CharField(max_length=50, blank=True, null=True)
    branches = models.ManyToManyField(Branch, through='ProductRegistry', related_name='products')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('branch', 'barcode')

    def __str__(self):
        return f"{self.name} - {self.barcode}"

    def active_combo_ids(self, branch):
        """Return a list of combo_id strings for active combos that include
        this product and are available at the given branch."""
        from core.models import ComboGroup
        combo_qs = ComboGroup.objects.filter(
            products=self,
            branches=branch,
            is_active=True
        ).values_list('combo_id', flat=True)
        return [cid for cid in combo_qs if cid]

class ComboPrice(models.Model):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='combos')
    branch = models.ForeignKey(Branch, on_delete=models.CASCADE, related_name='combos', null=True, blank=True)
    quantity = models.PositiveIntegerField(help_text='Number of units in this combo')
    price = models.DecimalField(max_digits=10, decimal_places=0, help_text='Total price for the quantity')
    class Meta:
        unique_together = ('product', 'branch', 'quantity')
        ordering = ['quantity']
    def __str__(self):
        branch_str = f" @ {self.branch.name}" if self.branch else ""
        return f"{self.quantity} pcs → ₹{self.price}{branch_str}"


class ComboGroup(models.Model):
    combo_id = models.CharField(max_length=50, unique=True, blank=True, null=True, db_index=True)
    name = models.CharField(max_length=200, help_text="e.g. Mix & Match Summer Promo")
    branches = models.ManyToManyField(Branch, related_name='combo_groups', blank=True)
    products = models.ManyToManyField(Product, related_name='combo_groups', blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def save(self, *args, **kwargs):
        if not self.combo_id:
            from django.db.models import Max
            import re
            max_num = 0
            # Exclude self if already saved but not having combo_id, though that shouldn't happen
            queryset = ComboGroup.objects.exclude(combo_id__isnull=True)
            if self.pk:
                queryset = queryset.exclude(pk=self.pk)
            for cb in queryset:
                match = re.search(r'\d+', cb.combo_id)
                if match:
                    num = int(match.group())
                    if num > max_num:
                        max_num = num
            if max_num == 0:
                max_id_qs = ComboGroup.objects.all()
                if self.pk:
                    max_id_qs = max_id_qs.exclude(pk=self.pk)
                max_id = max_id_qs.aggregate(max_id=Max('id'))['max_id'] or 0
                max_num = max_id
            
            next_num = max_num + 1
            candidate = f"CB-{next_num:04d}"
            while ComboGroup.objects.filter(combo_id=candidate).exists():
                next_num += 1
                candidate = f"CB-{next_num:04d}"
            self.combo_id = candidate
        super().save(*args, **kwargs)

    @property
    def distinct_products(self):
        seen = set()
        result = []
        for product in self.products.all():
            if product.barcode not in seen:
                seen.add(product.barcode)
                result.append(product)
        return result

    @property
    def distinct_products_count(self):
        return self.products.values('barcode').distinct().count()

    def __str__(self):
        return self.name


class ComboTier(models.Model):
    combo_group = models.ForeignKey(ComboGroup, on_delete=models.CASCADE, related_name='tiers')
    quantity = models.PositiveIntegerField(help_text="Quantity milestone (e.g. 2, 5, 10)")
    price = models.DecimalField(max_digits=12, decimal_places=0, help_text="Special price for this quantity milestone")

    class Meta:
        unique_together = ('combo_group', 'quantity')
        ordering = ['quantity']

    def __str__(self):
        return f"{self.combo_group.name} - {self.quantity} items for ₹{self.price}"


class ProductRegistry(models.Model):
    branch = models.ForeignKey(Branch, on_delete=models.CASCADE)
    product = models.ForeignKey(Product, on_delete=models.CASCADE)
    stock_quantity = models.IntegerField(default=0)
    damaged_qty = models.PositiveIntegerField(default=0)
    low_stock_threshold = models.IntegerField(default=10)  # New field for low stock alert level

    @property
    def combos(self):
        return self.product.combos.filter(branch=self.branch).order_by('quantity')

    @property
    def is_in_active_combo(self):
        try:
            # Try evaluating using prefetch cache
            groups = self.product.combo_groups.all()
            return any(g.is_active and self.branch in g.branches.all() for g in groups)
        except (AttributeError, ValueError):
            return self.product.combo_groups.filter(branches=self.branch, is_active=True).exists()

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('branch', 'product')
        verbose_name = "Branch-wise Product"
        verbose_name_plural = "Branch-wise Products"

    def __str__(self):
        return f"{self.product.name} at {self.branch.name}"

class StockTransaction(models.Model):
    TRANSACTION_TYPES = (
        ('IN', 'Stock In'),
        ('OUT', 'Stock Out (Sale)'),
        ('ADJ', 'Adjustment'),
        ('DMG', 'Damaged'),
    )
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='transactions')
    branch = models.ForeignKey(Branch, on_delete=models.CASCADE, related_name='transactions')
    transaction_type = models.CharField(max_length=5, choices=TRANSACTION_TYPES)
    quantity = models.IntegerField()  # Positive for IN/ADJ increase, Positive for OUT increase. We'll stick to absolute changes or always positive with type dictating operation. Let's use ALWAYS POSITIVE and use transaction_type for + or -. Or signed + / -. Let's use positive for quantity and rely on transaction_type.
    reference = models.CharField(max_length=100, blank=True, null=True) # e.g. "Bill #123", "Init", "Manual adjustment"
    user = models.ForeignKey('users.User', on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    
    def save(self, *args, **kwargs):
        if self.reference:
            self.reference = str(self.reference)[:100]
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.transaction_type} of {self.quantity} for {self.product.name} at {self.branch.name}"


class StockAdjustment(models.Model):
    """Audit-trail model for wrong-entry corrections using reconciliation logic."""
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='stock_adjustments')
    branch = models.ForeignKey(Branch, on_delete=models.CASCADE, related_name='stock_adjustments')
    # Snapshot at time of correction
    opening_balance = models.IntegerField()
    stock_in = models.IntegerField()
    stock_out = models.IntegerField()
    # The correction amount (e.g. -90 to remove 90 wrongly added units)
    correction_amount = models.IntegerField(help_text='Positive to add, negative to subtract')
    # Computed: Op + In - Out + Adj
    closing_stock = models.IntegerField()
    is_in_stock = models.BooleanField()
    reason = models.CharField(max_length=255, blank=True)
    user = models.ForeignKey('users.User', on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ['-created_at']

    def save(self, *args, **kwargs):
        if self.reason:
            self.reason = str(self.reason)[:255]
        super().save(*args, **kwargs)

    def __str__(self):
        sign = '+' if self.correction_amount >= 0 else ''
        return f"Adj {sign}{self.correction_amount} for {self.product.name} @ {self.branch.name} → Cl:{self.closing_stock}"

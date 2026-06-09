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
        super().save(*args, **kwargs)

    def __str__(self):
        if self.code:
            return f"{self.name} ({self.code})"
        return self.name


class Product(models.Model):
    name = models.CharField(max_length=200)
    barcode = models.CharField(max_length=50, unique=True, db_index=True)
    price = models.DecimalField(max_digits=10, decimal_places=0)

    size = models.CharField(max_length=50, blank=True, null=True)
    branches = models.ManyToManyField(Branch, through='ProductRegistry', related_name='products')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.name} - {self.barcode}"
class ComboPrice(models.Model):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='combos')
    quantity = models.PositiveIntegerField(help_text='Number of units in this combo')
    price = models.DecimalField(max_digits=10, decimal_places=0, help_text='Total price for the quantity')
    class Meta:
        unique_together = ('product', 'quantity')
        ordering = ['quantity']
    def __str__(self):
        return f"{self.quantity} pcs → ₹{self.price}"


class ProductRegistry(models.Model):
    branch = models.ForeignKey(Branch, on_delete=models.CASCADE)
    product = models.ForeignKey(Product, on_delete=models.CASCADE)
    stock_quantity = models.IntegerField(default=0)
    damaged_qty = models.PositiveIntegerField(default=0)
    low_stock_threshold = models.IntegerField(default=10)  # New field for low stock alert level

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('branch', 'product')
        verbose_name_plural = "Product Registries"

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
    created_at = models.DateTimeField(auto_now_add=True)
    
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
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def save(self, *args, **kwargs):
        if self.reason:
            self.reason = str(self.reason)[:255]
        super().save(*args, **kwargs)

    def __str__(self):
        sign = '+' if self.correction_amount >= 0 else ''
        return f"Adj {sign}{self.correction_amount} for {self.product.name} @ {self.branch.name} → Cl:{self.closing_stock}"

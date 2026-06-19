from django.db import models
from django.conf import settings
import uuid
# Import additional models defined in separate file

class Bill(models.Model):
    PAYMENT_CHOICES = (
        ('cash', 'Cash'),
        ('online', 'Online'),
        ('split', 'Split Payment'),
    )
    branch = models.ForeignKey('core.Branch', on_delete=models.CASCADE, related_name='bills')
    staff = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name='bills_created')
    customer_name = models.CharField(max_length=100, blank=True, null=True)
    customer_phone = models.CharField(max_length=15, blank=True, null=True)
    total_amount = models.DecimalField(max_digits=12, decimal_places=0, default=0)
    retail_price = models.DecimalField(max_digits=12, decimal_places=0, default=0)
    cash_amount = models.DecimalField(max_digits=12, decimal_places=0, default=0)
    online_amount = models.DecimalField(max_digits=12, decimal_places=0, default=0)
    payment_method = models.CharField(max_length=10, choices=PAYMENT_CHOICES, default='cash')
    share_id = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    sequence_number = models.PositiveIntegerField(null=True, blank=True, db_index=True)
    invoice_number = models.CharField(max_length=50, unique=True, null=True, blank=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    has_returns = models.BooleanField(default=False)


    @property
    def item_savings(self):
        from decimal import Decimal
        return sum((Decimal(str(item.savings)) for item in self.items.all()), Decimal('0'))

    @property
    def total_savings(self):
        from decimal import Decimal
        return Decimal(str(self.item_savings))

    @property
    def subtotal_amount(self):
        from decimal import Decimal
        return Decimal(str(self.total_amount)) - Decimal(str(self.retail_price))

    @property
    def original_subtotal(self):
        return self.subtotal_amount + self.total_savings

    def save(self, *args, **kwargs):
        if not self.invoice_number:
            max_seq = Bill.objects.filter(branch=self.branch).aggregate(models.Max('sequence_number'))['sequence_number__max'] or 0
            self.sequence_number = max_seq + 1
            prefix = self.branch.invoice_prefix or 'AG'
            self.invoice_number = f"{prefix}-{self.sequence_number:04d}"
        super().save(*args, **kwargs)

    def __str__(self):
        bill_num = self.invoice_number or f"#{self.id}"
        return f"Bill {bill_num} - {self.branch.name} - {self.total_amount}"

class BillItem(models.Model):
    bill = models.ForeignKey(Bill, on_delete=models.CASCADE, related_name='items')
    product = models.ForeignKey('core.Product', on_delete=models.CASCADE)
    quantity = models.PositiveIntegerField(default=1)
    returned_quantity = models.PositiveIntegerField(default=0)
    unit_price = models.DecimalField(max_digits=10, decimal_places=0)
    subtotal = models.DecimalField(max_digits=12, decimal_places=0)
    exchange_from = models.CharField(max_length=150, blank=True, null=True)

    @property
    def regular_total(self):
        from decimal import Decimal
        return Decimal(str(self.product.price)) * self.quantity

    @property
    def savings(self):
        from decimal import Decimal
        reg_total = self.regular_total
        sub = Decimal(str(self.subtotal))
        return reg_total - sub if reg_total > sub else Decimal('0')

    @property
    def is_combo_purchase(self):
        from core.models import ComboGroup
        from django.db.models import Sum, Min
        
        combo_group = ComboGroup.objects.filter(
            products=self.product,
            branches=self.bill.branch,
            is_active=True
        ).first()
        if not combo_group:
            return False
            
        # Get minimum quantity required for the combo
        min_combo_qty = combo_group.tiers.aggregate(min_qty=Min('quantity'))['min_qty']
        if not min_combo_qty:
            min_combo_qty = 1
            
        # Calculate total quantity of items in this bill belonging to this combo group
        total_group_qty = self.bill.items.filter(
            product__in=combo_group.products.all()
        ).aggregate(total_qty=Sum('quantity'))['total_qty'] or 0
        
        return total_group_qty >= min_combo_qty

    def save(self, *args, **kwargs):
        if self.subtotal is None:
            self.subtotal = self.unit_price * self.quantity
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.product.name} x {self.quantity}"

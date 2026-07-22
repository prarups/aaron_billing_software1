from django.db import models
from django.db.models import Max
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

    @property
    def total_quantity(self):
        return sum(item.quantity for item in self.items.all())

    @property
    def hsn_codes(self):
        codes = [item.product.size for item in self.items.all() if item.product.size]
        return ", ".join(sorted(list(set(codes))))

    @property
    def applied_combos(self):
        from core.models import ComboGroup
        
        bill_items = list(self.items.all())
        product_ids = [item.product_id for item in bill_items]
        
        potential_combos = ComboGroup.objects.filter(
            products__id__in=product_ids,
            branches=self.branch,
            is_active=True
        ).prefetch_related('products', 'tiers').distinct()
        
        valid_combos = []
        for combo in potential_combos:
            tiers = list(combo.tiers.all())
            min_qty = min(t.quantity for t in tiers) if tiers else 1
            
            cg_product_ids = {p.id for p in combo.products.all()}
            total_qty = sum(item.quantity for item in bill_items if item.product_id in cg_product_ids)
            
            if total_qty >= min_qty:
                valid_combos.append(combo.id)
                
        return ComboGroup.objects.filter(id__in=valid_combos)

    # Validation for combo pricing removed as per request

    @property
    def return_summary(self):
        approved_returns = self.return_requests.filter(status="A").select_related('replacement_product')
        if not approved_returns.exists():
            return None
            
        total_returned_value = 0
        total_replacement_value = 0
        total_net_difference = 0
        total_cash_paid = 0
        total_online_paid = 0
        return_payment_method = None
        
        for ret in approved_returns:
            ret_value = ret.bill_item.unit_price * ret.quantity if (ret.quantity > 0 and ret.bill_item) else 0
            total_returned_value += ret_value
            if ret.replacement_product:
                # Combo swap: bill_item is a combo purchase AND price_difference==0
                # → customer paid nothing extra, so Total Exchanged = ₹0
                is_combo_swap = (
                    ret.price_difference == 0
                    and ret.bill_item is not None
                    and ret.bill_item.is_combo_purchase
                )
                if is_combo_swap:
                    total_replacement_value += 0
                else:
                    total_replacement_value += ret_value + ret.price_difference

            total_net_difference += ret.price_difference
            total_cash_paid += ret.cash_amount
            total_online_paid += ret.online_amount
            if ret.payment_method:
                return_payment_method = ret.payment_method
                
        payment_method_display = {
            'cash': 'Cash',
            'online': 'Online',
            'split': 'Split Payment'
        }.get(return_payment_method, 'Cash')
        
        return {
            'total_returned_value': total_returned_value,
            'total_replacement_value': total_replacement_value,
            'net_difference': abs(total_net_difference),
            'cash_paid': total_cash_paid,
            'online_paid': total_online_paid,
            'has_positive_diff': total_net_difference > 0,
            'has_negative_diff': total_net_difference < 0,
            'payment_method_display': payment_method_display,
            'payment_method': return_payment_method,
        }

    def __str__(self):
        bill_num = self.invoice_number or f"#{self.id}"
        return f"Bill {bill_num} - {self.branch.name} - {self.total_amount}"

    def save(self, *args, **kwargs):
        from django.db.models import Max
        if not self.sequence_number:
            max_seq = Bill.objects.filter(branch=self.branch).aggregate(max_seq=Max('sequence_number'))['max_seq'] or 0
            self.sequence_number = max_seq + 1
        if not self.invoice_number:
            prefix = getattr(self.branch, 'invoice_prefix', None) or 'AG'
            self.invoice_number = f"{prefix}-{self.sequence_number:04d}"
        super().save(*args, **kwargs)

class BillItem(models.Model):
    bill = models.ForeignKey(Bill, on_delete=models.CASCADE, related_name='items')
    product = models.ForeignKey('core.Product', on_delete=models.CASCADE)
    quantity = models.PositiveIntegerField(default=1)
    returned_quantity = models.PositiveIntegerField(default=0)
    unit_price = models.DecimalField(max_digits=10, decimal_places=0)
    subtotal = models.DecimalField(max_digits=12, decimal_places=0)
    exchange_from = models.CharField(max_length=150, blank=True, null=True)
    combo_group = models.ForeignKey('core.ComboGroup', on_delete=models.SET_NULL, null=True, blank=True, related_name='bill_items')

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
    def combo_display_id(self):
        if self.combo_group and self.combo_group.combo_id:
            return self.combo_group.combo_id
        from core.models import ComboGroup

        combo_group = ComboGroup.objects.filter(
            products=self.product,
            branches=self.bill.branch,
            is_active=True
        ).prefetch_related('tiers', 'products').first()
        
        if combo_group and combo_group.combo_id:
            tiers = list(combo_group.tiers.all())
            if tiers:
                min_combo_qty = min(t.quantity for t in tiers)
                cg_product_ids = {p.id for p in combo_group.products.all()}
                total_group_qty = sum(item.quantity for item in self.bill.items.all() if item.product_id in cg_product_ids)
                if total_group_qty >= min_combo_qty:
                    return combo_group.combo_id

        return "Combo"

    @property
    def combo_name(self):
        if self.combo_group:
            return self.combo_group.name
        from core.models import ComboGroup

        combo_group = ComboGroup.objects.filter(
            products=self.product,
            branches=self.bill.branch,
            is_active=True
        ).prefetch_related('tiers', 'products').first()
        
        if combo_group:
            tiers = list(combo_group.tiers.all())
            if tiers:
                min_combo_qty = min(t.quantity for t in tiers)
                cg_product_ids = {p.id for p in combo_group.products.all()}
                total_group_qty = sum(item.quantity for item in self.bill.items.all() if item.product_id in cg_product_ids)
                if total_group_qty >= min_combo_qty:
                    return combo_group.name

        return "Combo Offer"

    @property
    def is_combo_purchase(self):
        if self.combo_group_id:
            return True
        from core.models import ComboGroup
        from django.db.models import Sum, Min

        combo_group = ComboGroup.objects.filter(
            products=self.product,
            branches=self.bill.branch,
            is_active=True
        ).prefetch_related('tiers', 'products').first()
        
        if not combo_group:
            return False

        # Get minimum quantity required for the combo using prefetched tiers
        tiers = list(combo_group.tiers.all())
        if not tiers:
            return False
        min_combo_qty = min(t.quantity for t in tiers)

        # Calculate total quantity of items in this bill belonging to this combo group using prefetched items
        cg_product_ids = {p.id for p in combo_group.products.all()}
        total_group_qty = sum(item.quantity for item in self.bill.items.all() if item.product_id in cg_product_ids)

        return total_group_qty >= min_combo_qty

    def save(self, *args, **kwargs):
        if self.subtotal is None:
            self.subtotal = self.unit_price * self.quantity
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.product.name} x {self.quantity}"


class BranchGoal(models.Model):
    branch = models.ForeignKey('core.Branch', on_delete=models.CASCADE, related_name='goals')
    month = models.DateField(help_text="First day of the target month (e.g., 2026-06-01)")
    target_sales = models.DecimalField(max_digits=12, decimal_places=0, default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('branch', 'month')

    def __str__(self):
        return f"{self.branch.name} Goal - {self.month.strftime('%B %Y')}: ₹{self.target_sales}"


from django.db import models
from django.conf import settings
from django.utils import timezone


class ReturnRequest(models.Model):
    class Status(models.TextChoices):
        PENDING = "P", "Pending"
        APPROVED = "A", "Approved"
        REJECTED = "R", "Rejected"
        EXPIRED = "E", "Expired"

    CONDITION_CHOICES = (
        ('GOOD', 'Good – Resellable'),
        ('DAMAGED', 'Damaged'),
    )
    ACTION_CHOICES = (
        ('REFUND', 'Refund'),
        ('EXCHANGE', 'Exchange'),
        ('EXCH_SAME', 'Exchange with same item (Another one)'),
    )

    invoice = models.ForeignKey('billing.Bill', on_delete=models.CASCADE, related_name='return_requests')
    bill_item = models.ForeignKey('billing.BillItem', on_delete=models.SET_NULL, null=True, blank=True, related_name='return_requests')
    product = models.ForeignKey('core.Product', on_delete=models.SET_NULL, null=True, blank=True)
    quantity = models.PositiveIntegerField(default=1)
    condition = models.CharField(max_length=10, choices=CONDITION_CHOICES, default='GOOD')
    action_type = models.CharField(max_length=10, choices=ACTION_CHOICES, default='REFUND')
    requested_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    product_name = models.CharField(max_length=120, blank=True)
    reason = models.TextField(blank=True)
    status = models.CharField(max_length=1, choices=Status.choices, default=Status.PENDING)
    requested_at = models.DateTimeField(default=timezone.now)
    expires_at = models.DateTimeField(blank=True, null=True)
    active_branch = models.ForeignKey('core.Branch', on_delete=models.SET_NULL, null=True, blank=True, related_name='active_returns')

    def save(self, *args, **kwargs):
        if not self.expires_at:
            self.expires_at = self.requested_at + timezone.timedelta(days=2)
        # Store product name for easy reference
        if self.product and not self.product_name:
            self.product_name = self.product.name
        super().save(*args, **kwargs)

    def __str__(self):
        return f"Return #{self.pk} – Invoice {self.invoice_id} – {self.get_status_display()}"


class CreditNote(models.Model):
    invoice = models.ForeignKey('billing.Bill', on_delete=models.CASCADE, related_name='credit_notes')
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    created_at = models.DateTimeField(auto_now_add=True)
    reason = models.TextField(blank=True)
    issued_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)

    def __str__(self):
        return f"CreditNote #{self.pk} – Invoice {self.invoice_id} – ₹{self.amount}"

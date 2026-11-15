from django.db import models
from django.conf import settings
from core.models import Product
from core.models import Branch

class Inventory(models.Model):
    product = models.ForeignKey(Product, on_delete=models.SET_NULL, null=True, blank=True, related_name='inventories')
    branch = models.ForeignKey(Branch, on_delete=models.CASCADE, related_name='inventories')
    quantity = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'inventory_inventory'
        verbose_name_plural = "Inventories"

    def __str__(self):
        return f"{self.product.name if self.product else 'Deleted'} @ {self.branch.name}: {self.quantity}"


class StockTransfer(models.Model):
    STATUS_CHOICES = (
        ('DRAFT', 'Draft'),
        ('COMPLETED', 'Completed'),
        ('CANCELLED', 'Cancelled'),
    )

    transfer_number = models.CharField(max_length=50, unique=True, db_index=True)
    from_branch = models.ForeignKey(Branch, on_delete=models.CASCADE, related_name='transfers_sent')
    to_branch = models.ForeignKey(Branch, on_delete=models.CASCADE, related_name='transfers_received')
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='transfers_created')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='COMPLETED')
    notes = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.transfer_number} ({self.from_branch.name} → {self.to_branch.name})"

    @property
    def total_items(self):
        return sum(item.quantity for item in self.items.all())


class StockTransferItem(models.Model):
    transfer = models.ForeignKey(StockTransfer, on_delete=models.CASCADE, related_name='items')
    product = models.ForeignKey(Product, on_delete=models.CASCADE)
    quantity = models.PositiveIntegerField()
    notes = models.CharField(max_length=255, blank=True, null=True)

    def __str__(self):
        return f"{self.quantity} x {self.product.name} ({self.transfer.transfer_number})"


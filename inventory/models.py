from django.db import models
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

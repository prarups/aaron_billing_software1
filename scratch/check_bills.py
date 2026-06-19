import os
import sys
import django

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from django.db.models import Sum
from billing.models import Bill, BillItem
from billing.return_models import ReturnRequest

print("ALL BILLS:")
for b in Bill.objects.all().order_by('created_at'):
    print(f"Bill ID={b.id} | Invoice={b.invoice_number} | Customer={b.customer_name} | Total={b.total_amount}")
    for item in b.items.all():
        print(f"  Item: {item.product.name} (Barcode: {item.product.barcode}) | Qty={item.quantity} | UnitPrice={item.unit_price} | Subtotal={item.subtotal}")

print("\nALL APPROVED RETURN REQUESTS:")
for r in ReturnRequest.objects.filter(status=ReturnRequest.Status.APPROVED):
    print(f"RetReq PK={r.pk} | Invoice={r.invoice.invoice_number} | Product={r.product.name if r.product else r.product_name} | Qty={r.quantity} | PriceDiff={r.price_difference}")

total_bills = Bill.objects.aggregate(t=Sum('total_amount'))['t'] or 0
total_diff = ReturnRequest.objects.filter(status=ReturnRequest.Status.APPROVED).aggregate(t=Sum('price_difference'))['t'] or 0
print(f"\nSum total_amount from Bills: {total_bills}")
print(f"Sum price_difference from ReturnRequest: {total_diff}")
print(f"Sum total_revenue: {total_bills + total_diff}")

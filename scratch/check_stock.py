import os
import sys
import django

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from core.models import Product, Branch, ProductRegistry, StockTransaction
from billing.return_models import ReturnRequest

p = Product.objects.filter(barcode="610078 M").first()
if not p:
    print("Product not found")
else:
    print(f"Product: {p.name} ({p.barcode}) - Price: {p.price}")
    for registry in ProductRegistry.objects.filter(product=p):
        print(f"Registry: Branch={registry.branch.name}, Stock={registry.stock_quantity}, Damaged={registry.damaged_qty}")
        
    print("\nTransactions:")
    for tx in StockTransaction.objects.filter(product=p).order_by('created_at'):
        print(f"Tx: {tx.created_at} | Type={tx.transaction_type} | Qty={tx.quantity} | Ref={tx.reference}")
        
    print("\nReturn Requests:")
    for ret in ReturnRequest.objects.filter(product=p):
        print(f"RetReq: PK={ret.pk} | Qty={ret.quantity} | Cond={ret.condition} | Action={ret.action_type} | RepProd={ret.replacement_product} | RepQty={ret.replacement_quantity}")

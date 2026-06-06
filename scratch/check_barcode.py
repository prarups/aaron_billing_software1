import os
import sys
import django

# Add project root to sys.path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from core.models import Product, ProductRegistry

p = Product.objects.filter(barcode='100985M').first()
print("Product:", p)
if p:
    print("Name:", p.name)
    print("Price:", p.price)
    print("Registries:")
    for r in ProductRegistry.objects.filter(product=p):
        print(f"  Branch: {r.branch.name}, Stock: {r.stock_quantity}, Threshold: {r.low_stock_threshold}")

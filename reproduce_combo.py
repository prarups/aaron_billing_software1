import sys
sys.path.append('d:\\antigravitygithu\\aaron_billing_software1')
import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from core.models import Branch, Product, ProductRegistry, ComboGroup
from billing.models import Bill, BillItem
from billing.return_views import _get_bill_items_data

# Create branch
branch, _ = Branch.objects.get_or_create(name="AARON_CHITTOOR", branch_code="10001")

# Create products
p1, _ = Product.objects.get_or_create(barcode="610041", defaults={'name': 'BRANDED PRINTED 2XL', 'price': 650})
p2, _ = Product.objects.get_or_create(barcode="610085", defaults={'name': 'BRANDED SHIRT', 'price': 649})

# Set stock
ProductRegistry.objects.update_or_create(branch=branch, product=p1, defaults={'stock_quantity': 500})
ProductRegistry.objects.update_or_create(branch=branch, product=p2, defaults={'stock_quantity': 500})

# Create combo group
cg, _ = ComboGroup.objects.get_or_create(name="Combo")
cg.branches.add(branch)
cg.products.add(p1, p2)

# Create bill
bill = Bill.objects.create(branch=branch, invoice_number="TEST-1", total_amount=650)
BillItem.objects.create(bill=bill, product=p1, quantity=1, unit_price=650, total_price=650)

# Run logic
items, _ = _get_bill_items_data(bill)
for item in items:
    print(f"Item: {item['product_name']}, is_combo: {item['is_combo']}")
    if item['is_combo']:
        print("  Combo Eligible Products:")
        for cp in item['combo_eligible_products']:
            print(f"    - {cp['name']} (Barcode: {cp['barcode']}) Stock: {cp['stock']}")

# Cleanup
bill.delete()

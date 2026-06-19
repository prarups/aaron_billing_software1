import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
import sys
sys.path = [p for p in sys.path if not p.endswith('scratch')]
sys.path.insert(0, os.getcwd())
django.setup()

from billing.models import Bill, BillItem
from core.models import Product, ComboGroup, ProductRegistry

def main():
    print("Checking Bill AN-0001:")
    bill = Bill.objects.filter(invoice_number="AN-0001").first()
    if not bill:
        print("Bill AN-0001 not found!")
        return
    
    print(f"Bill ID: {bill.id}")
    print(f"Branch: {bill.branch}")
    
    print("\nBill Items:")
    for item in bill.items.all():
        print(f"- Item ID: {item.id}, Product: {item.product} (ID: {item.product.id}), Unit Price: {item.unit_price}")
        
    print("\nCombo Groups active at branch:")
    combo_groups = ComboGroup.objects.filter(branches=bill.branch, is_active=True)
    for cg in combo_groups:
        print(f"- Combo Group: {cg.name} (ID: {cg.id})")
        products = list(cg.products.all())
        print(f"  Products inside: {[ (p.id, p.name) for p in products ]}")
        
        print("  Product registry entries for these products at this branch:")
        for p in products:
            reg = ProductRegistry.objects.filter(product=p, branch=bill.branch).first()
            if reg:
                print(f"    * Product {p.name} (ID: {p.id}): stock={reg.stock_quantity}, price={p.price}")
            else:
                print(f"    * Product {p.name} (ID: {p.id}): NOT REGISTERED AT THIS BRANCH!")

if __name__ == "__main__":
    main()

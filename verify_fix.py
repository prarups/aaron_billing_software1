import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from core.models import Product, Branch, ProductRegistry
from inventory.models import Inventory

def main():
    # Ensure a branch exists
    branch, _ = Branch.objects.get_or_create(name='Test Branch')
    # Create a product
    product = Product.objects.create(name='Test Product', barcode='TEST123', price=10.00)
    # Register product in branch
    ProductRegistry.objects.create(branch=branch, product=product, stock_quantity=5)
    # Create inventory entry
    inv = Inventory.objects.create(product=product, branch=branch, quantity=5)
    print('Created inventory:', inv)
    # Delete the product (should set inventory.product to NULL)
    product.delete()
    # Refresh inventory from DB
    inv.refresh_from_db()
    print('After product deletion, inventory product is', inv.product)
    # Clean up
    inv.delete()
    branch.delete()

if __name__ == '__main__':
    main()

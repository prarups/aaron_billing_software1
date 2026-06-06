import os
import django
from django.db import connection

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from core.models import ProductRegistry, Product, Branch

def migrate():
    print("Starting data migration from inventory_inventory to core_productregistry...")
    with connection.cursor() as cursor:
        # Check if table exists
        cursor.execute("SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_name = 'inventory_inventory')")
        if not cursor.fetchone()[0]:
            print("Legacy table inventory_inventory not found. Skipping migration.")
            return

        # Fetch data
        cursor.execute("SELECT product_id, branch_id, stock_quantity, low_stock_threshold, last_updated FROM inventory_inventory")
        rows = cursor.fetchall()
        
        migrated_count = 0
        for pid, bid, stock, low, last_upd in rows:
            try:
                # Get or create registry entry
                reg, created = ProductRegistry.objects.get_or_create(
                    product_id=pid,
                    branch_id=bid,
                    defaults={
                        'stock_quantity': stock,
                        'low_stock_threshold': low,
                        'created_at': last_upd,
                        'updated_at': last_upd
                    }
                )
                if not created:
                    reg.stock_quantity = stock
                    reg.low_stock_threshold = low
                    reg.save()
                migrated_count += 1
            except Exception as e:
                print(f"Error migrating product {pid} for branch {bid}: {e}")
        
        print(f"Successfully migrated {migrated_count} records.")

if __name__ == "__main__":
    migrate()

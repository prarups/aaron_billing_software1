import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
import sys
sys.path = [p for p in sys.path if not p.endswith('scratch')]
sys.path.insert(0, os.getcwd())
django.setup()

from core.models import ComboGroup, ProductRegistry, Branch

def main():
    print("All Combo Groups:")
    for cg in ComboGroup.objects.all():
        print(f"\nID: {cg.id}, Name: {cg.name}, Combo ID: {cg.combo_id}, Active: {cg.is_active}")
        print("  Branches:")
        for b in cg.branches.all():
            print(f"    - {b.name} (ID: {b.id})")
        print("  Products:")
        for p in cg.products.all():
            print(f"    - {p.name} (ID: {p.id}) Price: {p.price}")
            
    print("\nAll Branches:")
    for b in Branch.objects.all():
        print(f"Branch: {b.name} (ID: {b.id}, Code: {b.code})")

if __name__ == "__main__":
    main()

import os
import sys
import django

# Insert the workspace root at the absolute beginning of sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from core.models import ComboGroup
from billing.return_models import ReturnRequest

print("CORRECTING HISTORICAL COMBO EXCHANGES:")
corrected_count = 0

for ret in ReturnRequest.objects.all():
    if not ret.replacement_product:
        continue
        
    # Check if both products are in the same active combo group
    combo_group = ComboGroup.objects.filter(
        products=ret.product,
        branches=ret.invoice.branch,
        is_active=True
    ).first()
    
    if combo_group and combo_group.products.filter(id=ret.replacement_product.id).exists():
        # This was a combo exchange! Its price difference should be 0.00.
        if ret.price_difference != 0:
            print(f"Fixing ReturnRequest PK={ret.pk}: Changing PriceDiff from {ret.price_difference} to 0.00 (Combo Exchange)")
            ret.price_difference = 0
            ret.save()
            corrected_count += 1

print(f"\nDone! Corrected {corrected_count} return requests.")

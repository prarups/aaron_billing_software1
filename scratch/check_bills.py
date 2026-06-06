import os
import sys
import django

# Add project root to sys.path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from billing.models import Bill

print("All Bills in DB:")
for b in Bill.objects.all():
    print(f"ID: {b.id}, Invoice Number: {repr(b.invoice_number)}, Sequence: {b.sequence_number}, Branch: {b.branch.name}")

import os
import sys
import django

# Add project root to sys.path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from billing.models import Bill

bill = Bill.objects.filter(invoice_number__iexact='AN-0001').first()
print("Bill filter result:", bill)
if bill:
    print("Bill ID:", bill.id)
    print("Bill Invoice Number:", repr(bill.invoice_number))
else:
    print("Bill not found with filter!")

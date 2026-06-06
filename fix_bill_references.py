"""
One-time script to fix existing StockTransaction references.
Updates 'Bill #<id>' to 'Bill <invoice_number>' for all existing records.

Usage: python manage.py shell < fix_bill_references.py
"""
import os, django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from core.models import StockTransaction
from billing.models import Bill
import re

# Build a map of bill.id -> bill.invoice_number
bill_map = {b.id: b.invoice_number for b in Bill.objects.all() if b.invoice_number}

updated = 0
pattern = re.compile(r'^Bill #(\d+)$')

for txn in StockTransaction.objects.filter(reference__startswith='Bill #'):
    match = pattern.match(txn.reference)
    if match:
        bill_id = int(match.group(1))
        invoice_number = bill_map.get(bill_id)
        if invoice_number:
            txn.reference = f'Bill {invoice_number}'
            txn.save(update_fields=['reference'])
            updated += 1

print(f"Updated {updated} StockTransaction references from 'Bill #<id>' to 'Bill <invoice_number>'.")

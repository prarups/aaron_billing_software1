import django
import os

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'aaron_billing_software.settings')
django.setup()

from billing.return_models import ReturnRequest
from core.models import StockTransaction

def clean_refund_out_transactions():
    """Delete stray OUT StockTransaction entries linked to REFUND ReturnRequests.
    This is a one‑off cleanup for existing data where an OUT transaction was
    mistakenly recorded for a refund. It matches transactions whose reference
    contains the ReturnRequest primary key.
    """
    refunds = ReturnRequest.objects.filter(action_type='REFUND')
    total_deleted = 0
    for ret in refunds:
        deleted, _ = StockTransaction.objects.filter(
            transaction_type='OUT',
            reference__contains=f'Return #{ret.pk}'
        ).delete()
        total_deleted += deleted
    print(f"Deleted {total_deleted} stray OUT transactions for refunds.")

if __name__ == '__main__':
    clean_refund_out_transactions()

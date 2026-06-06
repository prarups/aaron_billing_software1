import os
import sys
import django

# Add the project root to python path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from core.models import Branch
from billing.models import Bill
from django.db import transaction

def populate_existing_bills():
    print("Starting population of existing bills...")
    with transaction.atomic():
        # Define unique prefixes for existing branches to prevent unique constraint violation
        prefixes = {
            1: 'AK',  # Arron Kavali
            2: 'AN',  # Arron Nellore
            3: 'CM',  # chennai_madhavarm
            4: 'AP',  # aaron_putter
            5: 'TB',  # Test Branch
        }
        for branch in Branch.objects.all():
            if branch.id in prefixes:
                branch.invoice_prefix = prefixes[branch.id]
                branch.save()
            
            prefix = branch.invoice_prefix or 'AG'
            bills = Bill.objects.filter(branch=branch).order_by('id')
            for i, bill in enumerate(bills, 1):
                bill.sequence_number = i
                bill.invoice_number = f"{prefix}-{i:04d}"
                bill.save()
            print(f"Populated {len(bills)} bills for branch '{branch.name}' using prefix '{prefix}'")
    print("Finished population!")

if __name__ == '__main__':
    populate_existing_bills()

import os
import sys
import django

# Add project root to sys.path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from core.models import Branch

print("All Branches:")
for b in Branch.objects.all():
    print(f"ID: {b.id}, Name: {b.name}")

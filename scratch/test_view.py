import os
import sys
import django

# Add project root to sys.path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from django.test import RequestFactory
from django.contrib.auth import get_user_model
from billing.return_views import get_bill_items_api

# Create mock request
rf = RequestFactory()
request = rf.get('/billing/return/bill-items/?invoice_id=AN-0001')

# Mock user login
User = get_user_model()
user = User.objects.filter(role='owner').first()
request.user = user

# Call the view
response = get_bill_items_api(request)
print("Response content:", response.content.decode('utf-8'))

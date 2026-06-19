import os
import django
import re

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
import sys
sys.path = [p for p in sys.path if not p.endswith('scratch')]
sys.path.insert(0, os.getcwd())
django.setup()

from django.test import RequestFactory
from django.contrib.auth import get_user_model
from billing.return_views import return_create_view

def main():
    factory = RequestFactory()
    request = factory.get('/return/', {'invoice_id': 'AN-0001'})
    
    User = get_user_model()
    user = User.objects.filter(is_superuser=True).first()
    request.user = user
    
    response = return_create_view(request)
    print("Status code:", response.status_code)
    
    html = response.content.decode('utf-8')
    
    # Extract all_products_json and bill_items_json from the HTML script using regex
    all_products_match = re.search(r'const allProducts\s*=\s*(.*?);', html)
    bill_items_match = re.search(r'const preloaded\s*=\s*(.*?);', html)
    
    if all_products_match:
        print("Embedded allProducts:")
        print(all_products_match.group(1))
    else:
        print("allProducts not found in HTML!")
        
    if bill_items_match:
        print("Embedded preloaded (bill items):")
        print(bill_items_match.group(1))
    else:
        print("preloaded not found in HTML!")

if __name__ == "__main__":
    main()

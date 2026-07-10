import os
import django
import json

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
import sys
sys.path = [p for p in sys.path if not p.endswith('scratch')]
sys.path.insert(0, os.getcwd())
django.setup()

from django.test import RequestFactory
from billing.return_views import get_bill_items_api

def main():
    factory = RequestFactory()
    # Mocking AJAX request for invoice AN-0001
    request = factory.get('/return/bill-items/', {'invoice_id': 'AN-0001'})
    
    # We need a user with active branch to bypass login_required decorator (or call the view directly)
    # Since we imported get_bill_items_api, let's look at what it does or bypass the login decorator.
    # To bypass login_required, we can mock request.user or call the underlying function if we extract its logic,
    # or just set request.user to an authenticated user.
    from django.contrib.auth.models import AnonymousUser
    from django.contrib.auth import get_user_model
    User = get_user_model()
    user = User.objects.filter(is_superuser=True).first()
    request.user = user
    
    response = get_bill_items_api(request)
    print("Status code:", response.status_code)
    data = json.loads(response.content.decode('utf-8'))
    print("JSON Response:")
    print(json.dumps(data, indent=2))

if __name__ == "__main__":
    main()

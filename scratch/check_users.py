import os
import sys
import django

# Add project root to sys.path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from users.models import User

for u in User.objects.all():
    print(f"User: {u.username}, Active Branch: {u.active_branch.name if u.active_branch else 'None'}")

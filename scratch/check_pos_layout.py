import os
import django
import sys

workspace_dir = "d:\\antigravitygithu\\aaron_billing_software1"
sys.path.insert(0, workspace_dir)

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from django.conf import settings
settings.ALLOWED_HOSTS = ['*']

from django.test import Client
from django.contrib.auth import get_user_model

User = get_user_model()
user = User.objects.filter(is_superuser=True).first() or User.objects.first()

client = Client()
client.force_login(user)

# POS Page
response_pos = client.get('/billing/')
html_pos = response_pos.content.decode('utf-8')

# Search for the <body tag
for line in html_pos.split('\n'):
    if '<body' in line:
        print("POS Body line:", line.strip())

# Search for the <aside tag
for line in html_pos.split('\n'):
    if '<aside' in line:
        print("POS Aside line:", line.strip())

# Check product page
response_prod = client.get('/core/products/')
html_prod = response_prod.content.decode('utf-8')
for line in html_prod.split('\n'):
    if '<body' in line:
        print("Prod Body line:", line.strip())

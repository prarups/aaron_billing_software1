import os
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from core.forms import ComboPriceFormSet

fs = ComboPriceFormSet()
print("PREFIX IS:", fs.prefix)

"""
ASGI config for config project.

It exposes the ASGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/6.0/howto/deployment/asgi/
"""

import os
import django
from django.core.asgi import get_asgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

# Import FastAPI app only after django.setup() is completed
from fastapi_app import app as fastapi_app
from starlette.routing import Router, Mount

# Django ASGI application
django_asgi_app = get_asgi_application()

# Use Starlette Router as the main ASGI application
application = Router(
    routes=[
        Mount("/fastapi", app=fastapi_app),
        Mount("/", app=django_asgi_app),
    ]
)

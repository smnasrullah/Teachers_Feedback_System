import os

from django.core.management import call_command
from django.core.wsgi import get_wsgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.prod")

application = get_wsgi_application()
app = application

if os.environ.get("REAL_ADMIN_PASSWORD"):
    call_command("bootstrap_admin", verbosity=0)

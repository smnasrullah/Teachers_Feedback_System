import re

from django.apps import apps
from django.conf import settings
from django.urls import include, path, re_path
from django.views.static import serve

handler403 = "apps.core.views.error_403"
handler404 = "apps.core.views.error_404"
handler500 = "apps.core.views.error_500"

urlpatterns = [
    path("i18n/", include("django.conf.urls.i18n")),
    path("", include("apps.accounts.urls")),
    path("", include("apps.academics.urls")),
    path("", include("apps.enrollment.urls")),
    path("", include("apps.feedback.urls")),
    path("", include("apps.reports.urls")),
    path("", include("apps.core.urls")),
]

if apps.is_installed("django.contrib.admin"):
    from django.contrib import admin

    urlpatterns.append(path("admin/", admin.site.urls))

if settings.DEBUG:
    # Uploaded avatars and photos for the dev server only; a proxy serves them in production.
    urlpatterns.append(
        re_path(
            rf"^{re.escape(settings.MEDIA_URL.lstrip('/'))}(?P<path>.*)$",
            serve,
            {"document_root": settings.MEDIA_ROOT},
            name="media",
        )
    )

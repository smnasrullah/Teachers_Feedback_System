from django.apps import apps
from django.urls import include, path

handler403 = "apps.core.views.error_403"
handler404 = "apps.core.views.error_404"
handler500 = "apps.core.views.error_500"

urlpatterns = [
    path("i18n/", include("django.conf.urls.i18n")),
    path("", include("apps.accounts.urls")),
    path("", include("apps.academics.urls")),
    path("", include("apps.enrollment.urls")),
    path("", include("apps.core.urls")),
]

if apps.is_installed("django.contrib.admin"):
    from django.contrib import admin

    urlpatterns.append(path("admin/", admin.site.urls))

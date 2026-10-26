from django.urls import include, path

handler403 = "apps.core.views.error_403"
handler404 = "apps.core.views.error_404"
handler500 = "apps.core.views.error_500"

urlpatterns = [
    path("i18n/", include("django.conf.urls.i18n")),
    path("", include("apps.core.urls")),
]

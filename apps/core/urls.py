from django.urls import path

from . import admin_views, views

app_name = "core"

urlpatterns = [
    path("", views.home, name="home"),
    path("time", views.server_time, name="server_time"),
    path("healthz", views.healthz, name="healthz"),
    path("manage/settings/", admin_views.settings_page, name="settings"),
    path("dev/gallery", views.dev_gallery, name="dev_gallery"),
]

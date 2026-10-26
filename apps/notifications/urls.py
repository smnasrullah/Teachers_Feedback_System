from django.urls import path

from . import admin_views, views

app_name = "notifications"

urlpatterns = [
    path("notifications/badge/", views.badge, name="badge"),
    path("notifications/list/", views.bell_list, name="list"),
    path("notifications/read-all/", views.read_all, name="read_all"),
    path("notifications/<int:pk>/open/", views.open_notice, name="open"),
    path("manage/notifications/templates/", admin_views.template_list, name="template_list"),
    path(
        "manage/notifications/templates/<str:kind>/",
        admin_views.template_edit,
        name="template_edit",
    ),
    path(
        "manage/notifications/templates/<str:kind>/test/",
        admin_views.template_test,
        name="template_test",
    ),
    path("manage/notifications/log/", admin_views.delivery_log, name="log"),
]

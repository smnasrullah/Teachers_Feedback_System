from django.urls import path

from . import views

app_name = "auditlog"

urlpatterns = [
    path("manage/audit-log/", views.log, name="log"),
    path("manage/audit-log/export/", views.export, name="export"),
    path("manage/audit-log/verify/", views.verify, name="verify"),
]

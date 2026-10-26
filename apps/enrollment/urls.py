from django.urls import path

from . import views

app_name = "enrollment"

urlpatterns = [
    path("manage/enrollment/group/", views.group_enroll, name="group"),
    path("manage/enrollment/", views.enrollment_list, name="list"),
    path("manage/enrollment/<int:pk>/remove/", views.enrollment_remove, name="remove"),
    path("manage/enrollment/missing/", views.missing_enrollment, name="missing"),
]

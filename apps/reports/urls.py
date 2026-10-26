from django.urls import path

from . import admin_views, hod_views, views

app_name = "reports"

urlpatterns = [
    path("teacher/courses/", views.overview, name="overview"),
    path("teacher/courses/<int:offering_id>/<int:window_id>/", views.course, name="course"),
    path(
        "teacher/courses/<int:offering_id>/<int:window_id>/comments/<int:question_id>/",
        views.comments,
        name="comments",
    ),
    path(
        "teacher/courses/<int:offering_id>/<int:window_id>/report-comment/",
        views.report_comment,
        name="report_comment",
    ),
    path(
        "teacher/courses/<int:offering_id>/<int:window_id>/print/",
        views.print_view,
        name="print",
    ),
    path(
        "teacher/courses/<int:offering_id>/<int:window_id>/note/",
        views.save_note,
        name="note",
    ),
    path("manage/analytics/", admin_views.analytics, name="analytics"),
    path("hod/pending/", hod_views.pending, name="hod_pending"),
    path("hod/pending/remind/", hod_views.remind, name="hod_remind"),
    path("hod/audit/", hod_views.audit, name="hod_audit"),
]

from django.urls import path

from . import views

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
        "teacher/courses/<int:offering_id>/<int:window_id>/print/",
        views.print_view,
        name="print",
    ),
    path(
        "teacher/courses/<int:offering_id>/<int:window_id>/note/",
        views.save_note,
        name="note",
    ),
]

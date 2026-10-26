from django.urls import path

from . import filter_views, question_views, student_views, window_views

app_name = "feedback"

urlpatterns = [
    path(
        "feedback/<int:window_id>/<int:offering_id>/",
        student_views.feedback_form,
        name="form",
    ),
    path(
        "feedback/<int:window_id>/<int:offering_id>/draft/",
        student_views.draft,
        name="draft",
    ),
    path(
        "feedback/<int:window_id>/<int:offering_id>/check/<int:question_id>/",
        student_views.precheck,
        name="precheck",
    ),
    path(
        "feedback/<int:window_id>/<int:offering_id>/done/",
        student_views.done,
        name="done",
    ),
    path("manage/questions/", question_views.question_list, name="questions"),
    path("manage/questions/new/", question_views.question_create, name="question_create"),
    path("manage/questions/order/", question_views.question_reorder, name="question_reorder"),
    path("manage/questions/<int:pk>/", question_views.question_edit, name="question_edit"),
    path(
        "manage/questions/<int:pk>/duplicate/",
        question_views.question_duplicate,
        name="question_duplicate",
    ),
    path(
        "manage/questions/<int:pk>/toggle/", question_views.question_toggle, name="question_toggle"
    ),
    path("manage/question-categories/", question_views.category_list, name="categories"),
    path(
        "manage/question-categories/<int:pk>/", question_views.category_edit, name="category_edit"
    ),
    path("manage/filter-words/", filter_views.filter_terms_view, name="filter_terms"),
    path(
        "manage/filter-words/<int:pk>/delete/",
        filter_views.filter_term_delete,
        name="filter_term_delete",
    ),
    path("manage/moderation/", filter_views.moderation_queue, name="moderation"),
    path(
        "manage/moderation/<uuid:pk>/",
        filter_views.moderation_decide,
        name="moderation_decide",
    ),
    path("manage/feedback-rounds/", window_views.window_list, name="windows"),
    path("manage/feedback-rounds/new/", window_views.window_create, name="window_create"),
    path("manage/feedback-rounds/<int:pk>/", window_views.window_edit, name="window_edit"),
    path(
        "manage/feedback-rounds/<int:pk>/preview/",
        window_views.window_preview,
        name="window_preview",
    ),
]

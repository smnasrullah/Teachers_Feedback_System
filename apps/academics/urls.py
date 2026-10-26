from django.urls import path

from . import import_views, promotion_views, result_views, views

app_name = "academics"

urlpatterns = [
    path("manage/teaching/assign/", views.assign_teachers, name="assign_teachers"),
    path("manage/import/", import_views.import_index, name="import_index"),
    path("manage/import/<slug:kind>/", import_views.import_upload, name="import_upload"),
    path("manage/import/<slug:kind>/apply/", import_views.import_apply, name="import_apply"),
    path(
        "manage/import/<slug:kind>/template.csv",
        import_views.import_template,
        name="import_template",
    ),
    path("manage/results/", result_views.result_index, name="results"),
    path("manage/results/<int:pk>/", result_views.grade_sheet, name="grade_sheet"),
    path("manage/promotion/", promotion_views.promotion_preview, name="promotion"),
    path("manage/promotion/rule/", promotion_views.promotion_rule, name="promotion_rule"),
    path(
        "manage/promotion/<int:semester_pk>/apply/",
        promotion_views.promotion_confirm,
        name="promotion_confirm",
    ),
    path(
        "manage/promotion/<int:semester_pk>/override/<int:student_pk>/",
        promotion_views.promotion_override,
        name="promotion_override",
    ),
    path("manage/academics/<slug:entity>/", views.entity_list, name="list"),
    path("manage/academics/<slug:entity>/new/", views.entity_create, name="create"),
    path("manage/academics/<slug:entity>/<int:pk>/", views.entity_edit, name="edit"),
    path("manage/academics/<slug:entity>/<int:pk>/delete/", views.entity_delete, name="delete"),
]

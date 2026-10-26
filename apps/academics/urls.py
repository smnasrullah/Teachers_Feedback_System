from django.urls import path

from . import import_views, views

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
    path("manage/academics/<slug:entity>/", views.entity_list, name="list"),
    path("manage/academics/<slug:entity>/new/", views.entity_create, name="create"),
    path("manage/academics/<slug:entity>/<int:pk>/", views.entity_edit, name="edit"),
    path("manage/academics/<slug:entity>/<int:pk>/delete/", views.entity_delete, name="delete"),
]

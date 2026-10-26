from django.urls import path

from . import views

app_name = "academics"

urlpatterns = [
    path("manage/academics/<slug:entity>/", views.entity_list, name="list"),
    path("manage/academics/<slug:entity>/new/", views.entity_create, name="create"),
    path("manage/academics/<slug:entity>/<int:pk>/", views.entity_edit, name="edit"),
    path("manage/academics/<slug:entity>/<int:pk>/delete/", views.entity_delete, name="delete"),
]

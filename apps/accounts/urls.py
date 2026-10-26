from django.urls import path

from .views import registry, users

app_name = "accounts"

urlpatterns = [
    path("manage/registry/", registry.registry_list, name="registry_list"),
    path("manage/registry/bulk/", registry.registry_bulk, name="registry_bulk"),
    path("manage/registry/new/<str:id_type>/", registry.registry_create, name="registry_create"),
    path("manage/registry/<int:pk>/", registry.registry_edit, name="registry_edit"),
    path("manage/registry/<int:pk>/hod/", registry.registry_hod, name="registry_hod"),
    path("manage/users/", users.user_list, name="user_list"),
    path("manage/users/<int:pk>/", users.user_detail, name="user_detail"),
    path("manage/users/<int:pk>/role/", users.user_role, name="user_role"),
]

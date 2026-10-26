"""URLs used only by tests/test_permissions.py to exercise deny-by-default."""

from django.http import HttpResponse
from django.urls import include, path
from django.views import View

from apps.core.permissions import HOD, PublicMixin, Role, RoleRequiredMixin, public, role_required


def unmarked(request):
    return HttpResponse("leak")


@public
def open_page(request):
    return HttpResponse("open")


@role_required(Role.ADMIN)
def admin_only(request):
    return HttpResponse("admin")


class HodView(RoleRequiredMixin, View):
    allowed_roles = (HOD, Role.ADMIN)

    def get(self, request):
        return HttpResponse("hod")


class OpenView(PublicMixin, View):
    def get(self, request):
        return HttpResponse("open view")


urlpatterns = [
    path("unmarked/", unmarked, name="unmarked"),
    path("open/", open_page, name="open"),
    path("admin-only/", admin_only, name="admin_only"),
    path("hod/", HodView.as_view(), name="hod"),
    path("open-view/", OpenView.as_view(), name="open_view"),
    # The login redirect target (``settings.LOGIN_URL``) must resolve in this URLconf too.
    path("accounts/", include(([path("login/", open_page, name="login")], "accounts"))),
]

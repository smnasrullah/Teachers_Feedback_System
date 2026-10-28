"""The development-only Django admin: the Admin role uses it, nobody else gets in, no crash."""

import pytest
from django.test import Client
from django.urls import reverse

from apps.core.permissions import Role
from tests.factories import make_admin, make_user, sign_in

ADMIN_PAGES = ("admin:index", "admin:auth_group_changelist", "admin:axes_accessattempt_changelist")


@pytest.fixture
def admin_client(db):
    client = Client(HTTP_ACCEPT_LANGUAGE="en")
    sign_in(client, make_admin())
    return client


@pytest.mark.parametrize("name", ADMIN_PAGES)
def test_the_admin_role_opens_the_django_admin(admin_client, name):
    assert admin_client.get(reverse(name)).status_code == 200


@pytest.mark.parametrize("role", [Role.STUDENT, Role.TEACHER])
def test_other_roles_are_turned_away_without_an_error(db, role):
    client = Client(HTTP_ACCEPT_LANGUAGE="en")
    sign_in(client, make_user(f"{role[:3]}_crawl", role))

    assert client.get(reverse("admin:login")).status_code == 200
    index = client.get(reverse("admin:index"))
    assert index.status_code == 302
    assert index["Location"].startswith(reverse("admin:login"))


def test_permissions_follow_the_role(db):
    admin = make_admin()
    student = make_user("stu_perm", Role.STUDENT)

    assert admin.has_perm("auth.view_group") and admin.has_module_perms("axes")
    assert not student.has_perm("auth.view_group") and not student.has_module_perms("axes")
    admin.is_active = False
    assert not admin.has_perm("auth.view_group") and not admin.has_module_perms("axes")

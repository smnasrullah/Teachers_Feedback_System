from dataclasses import dataclass

import pytest
from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import ImproperlyConfigured, PermissionDenied
from django.http import Http404
from django.test import RequestFactory
from django.urls import URLPattern, URLResolver, get_resolver

from apps.core.permissions import (
    HOD,
    PUBLIC,
    Role,
    ScopedQuerysetMixin,
    access_policy_of,
    get_scoped_object_or_404,
    has_role,
    is_exempt,
    primary_role,
    role_required,
    user_roles,
)
from tests.testapp import urls as policy_urls

# Every URL reachable without login. Adding a public page means adding it here, on review.
PUBLIC_VIEWS = {
    "core:home",
    "core:healthz",
    "core:dev_gallery",
    # Sign-up, login, second factor and recovery run before anyone is signed in.
    "accounts:login",
    "accounts:login_second_factor",
    "accounts:login_two_factor_setup",
    "accounts:logout",
    "accounts:signup",
    "accounts:signup_contact",
    "accounts:signup_verify",
    "accounts:signup_resend",
    "accounts:signup_password",
    "accounts:password_forgot",
    "accounts:password_forgot_verify",
    "accounts:password_forgot_resend",
    "accounts:password_forgot_new",
    "accounts:username_forgot",
    "accounts:username_forgot_verify",
    "accounts:username_forgot_resend",
}


@dataclass
class StubUser:
    role: str | None
    is_hod: bool = False
    is_active: bool = True
    is_authenticated: bool = True
    pk: int = 1


def iter_patterns(resolver=None, prefix="", namespaces=()):
    resolver = resolver or get_resolver()
    for entry in resolver.url_patterns:
        if isinstance(entry, URLResolver):
            nested = (*namespaces, entry.namespace) if entry.namespace else namespaces
            yield from iter_patterns(entry, prefix + str(entry.pattern), nested)
        elif isinstance(entry, URLPattern):
            name = ":".join((*namespaces, entry.name)) if entry.name else ""
            yield prefix + str(entry.pattern), name, namespaces, entry.callback


def test_every_url_declares_an_access_policy():
    missing = [
        route
        for route, name, namespaces, callback in iter_patterns()
        if access_policy_of(callback) is None and not is_exempt(name, namespaces)
    ]
    assert missing == [], f"URLs without @public/@role_required: {missing}"


def test_public_urls_are_allow_listed():
    public_names = {
        name for _, name, _, callback in iter_patterns() if access_policy_of(callback) == PUBLIC
    }
    assert public_names <= PUBLIC_VIEWS, f"Unreviewed public URLs: {public_names - PUBLIC_VIEWS}"


@pytest.mark.parametrize(
    ("user", "expected"),
    [
        (AnonymousUser(), set()),
        (StubUser(role=None), set()),
        (StubUser(role="superuser"), set()),
        (StubUser(role=Role.ADMIN, is_active=False), set()),
        (StubUser(role=Role.STUDENT), {Role.STUDENT}),
        (StubUser(role=Role.STUDENT, is_hod=True), {Role.STUDENT}),
        (StubUser(role=Role.TEACHER), {Role.TEACHER}),
        (StubUser(role=Role.TEACHER, is_hod=True), {Role.TEACHER, HOD}),
        (StubUser(role=Role.ADMIN), {Role.ADMIN}),
    ],
)
def test_user_roles(user, expected):
    assert user_roles(user) == expected


def test_primary_role_and_has_role():
    hod = StubUser(role=Role.TEACHER, is_hod=True)
    assert primary_role(hod) == HOD
    assert has_role(hod, HOD)
    assert not has_role(hod, Role.ADMIN)
    assert primary_role(None) == ""


def test_role_required_rejects_bad_configuration():
    with pytest.raises(ImproperlyConfigured):
        role_required()
    with pytest.raises(ImproperlyConfigured):
        role_required("owner")


@pytest.mark.urls(policy_urls.__name__)
class TestDenyByDefault:
    def test_view_without_policy_is_refused(self, client, db):
        response = client.get("/unmarked/")
        assert response.status_code == 403
        assert b"leak" not in response.content

    def test_public_views_are_served(self, client, db):
        assert client.get("/open/").status_code == 200
        assert client.get("/open-view/").status_code == 200

    def test_anonymous_is_sent_to_login(self, client, db):
        response = client.get("/admin-only/")
        assert response.status_code == 302
        assert "next=/admin-only/" in response["Location"]


def call(view, user):
    request = RequestFactory().get("/")
    request.user = user
    return view(request)


@pytest.mark.parametrize(
    ("user", "status"),
    [
        (StubUser(role=Role.STUDENT), 403),
        (StubUser(role=Role.TEACHER), 403),
        (StubUser(role=Role.ADMIN), 200),
    ],
)
def test_function_view_role_matrix(user, status):
    if status == 403:
        with pytest.raises(PermissionDenied):
            call(policy_urls.admin_only, user)
    else:
        assert call(policy_urls.admin_only, user).status_code == status


@pytest.mark.parametrize(
    ("user", "allowed"),
    [
        (StubUser(role=Role.STUDENT), False),
        (StubUser(role=Role.TEACHER), False),
        (StubUser(role=Role.TEACHER, is_hod=True), True),
        (StubUser(role=Role.ADMIN), True),
    ],
)
def test_class_view_role_matrix(user, allowed):
    view = policy_urls.HodView.as_view()
    assert access_policy_of(view) == {HOD, Role.ADMIN}
    if allowed:
        assert call(view, user).status_code == 200
    else:
        with pytest.raises(PermissionDenied):
            call(view, user)


def test_role_mixin_without_roles_fails_at_url_load():
    class NoRoles(policy_urls.RoleRequiredMixin, policy_urls.View):
        pass

    with pytest.raises(ImproperlyConfigured):
        NoRoles.as_view()


@pytest.mark.django_db
def test_scoped_lookup_hides_out_of_scope_rows(django_user_model):
    mine = django_user_model.objects.create(username="mine")
    other = django_user_model.objects.create(username="other")

    def own_rows(queryset, user):
        return queryset.filter(pk=user.pk)

    queryset = django_user_model.objects.all()
    assert get_scoped_object_or_404(queryset, own_rows, mine, pk=mine.pk) == mine
    with pytest.raises(Http404):
        get_scoped_object_or_404(queryset, own_rows, mine, pk=other.pk)


@pytest.mark.django_db
def test_scoped_queryset_mixin_defaults_to_nothing(django_user_model):
    django_user_model.objects.create(username="someone")

    class Base:
        def get_queryset(self):
            return django_user_model.objects.all()

    class View(ScopedQuerysetMixin, Base):
        pass

    view = View()
    view.request = RequestFactory().get("/")
    view.request.user = StubUser(role=Role.ADMIN)
    assert list(view.get_queryset()) == []

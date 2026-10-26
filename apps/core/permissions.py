"""Roles and deny-by-default access control (BLUEPRINT §5.3).

Every view declares an access policy with ``@public`` / ``PublicMixin`` or
``@role_required`` / ``RoleRequiredMixin``. ``AccessPolicyMiddleware`` refuses any view
without one, and ``tests/test_permissions.py`` fails the build for such a URL.
Object access goes through a user-scoped queryset so out-of-scope rows look missing (404).
"""

from collections.abc import Callable, Iterable
from functools import wraps

from django.conf import settings
from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import ImproperlyConfigured, PermissionDenied
from django.db import models
from django.shortcuts import get_object_or_404
from django.utils.translation import gettext_lazy as _


class Role(models.TextChoices):
    STUDENT = "student", _("Student")
    TEACHER = "teacher", _("Teacher")
    ADMIN = "admin", _("Admin")


# HOD is not a stored role: it is a teacher whose profile carries the HOD flag.
HOD = "hod"
ALL_ROLES = frozenset({*Role.values, HOD})
ROLE_PRECEDENCE = (Role.ADMIN.value, HOD, Role.TEACHER.value, Role.STUDENT.value)

ACCESS_POLICY_ATTR = "access_policy"
PUBLIC = "public"


def user_roles(user) -> frozenset[str]:
    """Roles held by ``user``; empty for anonymous, inactive or role-less users."""
    if not getattr(user, "is_authenticated", False) or not getattr(user, "is_active", False):
        return frozenset()
    role = getattr(user, "role", None)
    if role not in Role.values:
        return frozenset()
    if role == Role.TEACHER and getattr(user, "is_hod", False):
        return frozenset({role, HOD})
    return frozenset({role})


def has_role(user, *roles: str) -> bool:
    return not user_roles(user).isdisjoint(roles)


def primary_role(user) -> str:
    """The most privileged role held, or ``""``."""
    held = user_roles(user)
    return next((role for role in ROLE_PRECEDENCE if role in held), "")


def _validated(roles: Iterable[str]) -> frozenset[str]:
    allowed = frozenset(roles)
    if not allowed or not allowed <= ALL_ROLES:
        raise ImproperlyConfigured(
            f"Allowed roles must be a non-empty subset of {sorted(ALL_ROLES)}."
        )
    return allowed


def _gate(request, allowed: frozenset[str]):
    """Login redirect for anonymous users, 403 for the wrong role, ``None`` when allowed."""
    if not request.user.is_authenticated:
        return redirect_to_login(request.get_full_path())
    if user_roles(request.user).isdisjoint(allowed):
        raise PermissionDenied
    return None


def access_policy_of(view) -> frozenset[str] | str | None:
    return getattr(view, ACCESS_POLICY_ATTR, None)


def is_exempt(view_name: str, namespaces: Iterable[str]) -> bool:
    """Third-party URLs that enforce their own access (configured in settings)."""
    return view_name in settings.ACCESS_POLICY_EXEMPT_VIEWS or not set(namespaces).isdisjoint(
        settings.ACCESS_POLICY_EXEMPT_NAMESPACES
    )


def public(view: Callable) -> Callable:
    """Mark a function view as reachable without login. Must also be allow-listed in tests."""
    setattr(view, ACCESS_POLICY_ATTR, PUBLIC)
    return view


def role_required(*roles: str) -> Callable[[Callable], Callable]:
    allowed = _validated(roles)

    def decorator(view: Callable) -> Callable:
        @wraps(view)
        def wrapper(request, *args, **kwargs):
            return _gate(request, allowed) or view(request, *args, **kwargs)

        setattr(wrapper, ACCESS_POLICY_ATTR, allowed)
        return wrapper

    return decorator


class PublicMixin:
    @classmethod
    def as_view(cls, **initkwargs):
        view = super().as_view(**initkwargs)
        setattr(view, ACCESS_POLICY_ATTR, PUBLIC)
        return view


class RoleRequiredMixin:
    """Class-based twin of ``role_required``; set ``allowed_roles`` on the view."""

    allowed_roles: Iterable[str] = ()

    @classmethod
    def as_view(cls, **initkwargs):
        allowed = _validated(initkwargs.get("allowed_roles", cls.allowed_roles))
        view = super().as_view(**initkwargs)
        setattr(view, ACCESS_POLICY_ATTR, allowed)
        return view

    def dispatch(self, request, *args, **kwargs):
        return _gate(request, _validated(self.allowed_roles)) or super().dispatch(
            request, *args, **kwargs
        )


def get_scoped_object_or_404(queryset, scope: Callable, user, **lookup):
    """Fetch one row through ``scope(queryset, user)``; rows outside the scope 404 (IDOR)."""
    return get_object_or_404(scope(queryset, user), **lookup)


class ScopedQuerysetMixin:
    """For single/multiple object views: rows come only from ``scope_queryset``.

    The default scope is empty, so a view that forgets to define one shows nothing.
    """

    def get_queryset(self):
        return self.scope_queryset(super().get_queryset(), self.request.user)

    def scope_queryset(self, queryset, user):
        return queryset.none()

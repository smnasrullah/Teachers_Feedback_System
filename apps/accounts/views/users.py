"""Admin screens for accounts: list, detail and role assignment."""

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext as _
from django.views.decorators.http import require_GET, require_POST

from apps.accounts.forms import RoleForm, UserFilterForm
from apps.accounts.models import User
from apps.accounts.services import roles
from apps.core.permissions import Role, role_required
from apps.core.services.navigation import admin_nav_items

PAGE_SIZE = 50


@require_GET
@role_required(Role.ADMIN)
def user_list(request):
    form = UserFilterForm(request.GET)
    users = User.objects.select_related("department").order_by("-date_joined", "-id")
    if form.is_valid():
        data = form.cleaned_data
        if data["q"]:
            term = data["q"].strip()
            users = users.filter(Q(username__icontains=term) | Q(nickname__icontains=term))
        if data["role"]:
            users = users.filter(role=data["role"])
    else:
        users = users.none()
    page_obj = Paginator(users, PAGE_SIZE).get_page(request.GET.get("page"))
    params = request.GET.copy()
    params.pop("page", None)
    return render(
        request,
        "admin_panel/user_list.html",
        {
            "nav_items": admin_nav_items("users"),
            "filter_form": form,
            "page_obj": page_obj,
            "query": f"{params.urlencode()}&" if params else "",
        },
    )


@require_GET
@role_required(Role.ADMIN)
def user_detail(request, pk):
    account = get_object_or_404(User.objects.select_related("department"), pk=pk)
    registry = getattr(account, "registry", None)
    can_change_role = account.role in roles.CHANGEABLE_ROLES and account.pk != request.user.pk
    return render(
        request,
        "admin_panel/user_detail.html",
        {
            "nav_items": admin_nav_items("users"),
            "account": account,
            "registry": registry,
            "role_form": RoleForm(initial={"role": account.role}) if can_change_role else None,
        },
    )


@require_POST
@role_required(Role.ADMIN)
def user_role(request, pk):
    account = get_object_or_404(User, pk=pk)
    form = RoleForm(request.POST)
    if not form.is_valid():
        messages.error(request, _("Choose a valid role."))
    else:
        try:
            changed = roles.change_role(
                account, form.cleaned_data["role"], actor=request.user, request=request
            )
        except ValidationError as error:
            for message in error.messages:
                messages.error(request, message)
        else:
            if changed:
                messages.success(request, _("The role was changed."))
    return redirect("accounts:user_detail", pk=pk)

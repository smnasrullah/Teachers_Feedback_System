"""Account screens: the Admin's list, detail and role assignment, and password reset codes
(Admin for anyone, a head of department for their own department)."""

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.translation import gettext as _
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from apps.accounts import ratelimits
from apps.accounts.forms import ResetCodeLookupForm, RoleForm, UserFilterForm
from apps.accounts.guards import step_up_required
from apps.accounts.models import User
from apps.accounts.services import registry as registry_service
from apps.accounts.services import roles, twofactor
from apps.core.permissions import HOD, Role, role_required
from apps.core.services.navigation import admin_nav_items, user_nav_items

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
@step_up_required
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
            "can_issue_reset_code": registry_service.can_issue_reset_code(account, request.user),
            "second_factor": twofactor.required_for(account),
        },
    )


@require_POST
@role_required(Role.ADMIN)
@step_up_required
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


def _issue_reset_code(request, account, back_url: str):
    """Issue the code and show it this once (the page is never cached)."""
    try:
        issued = registry_service.issue_reset_code(account, actor=request.user, request=request)
    except ValidationError as error:
        for message in error.messages:
            messages.error(request, message)
        return redirect(back_url)
    return render(
        request,
        "accounts/reset_code_done.html",
        {
            "nav_items": user_nav_items(request.user, "reset_code"),
            "account": account,
            "issued": issued,
            "back_url": back_url,
        },
    )


@require_POST
@never_cache
@role_required(Role.ADMIN)
@step_up_required
def user_reset_code(request, pk):
    account = get_object_or_404(User, pk=pk)
    return _issue_reset_code(request, account, reverse("accounts:user_detail", args=[pk]))


@require_http_methods(["GET", "POST"])
@never_cache
@ratelimits.limited(ratelimits.registry_id, ip_rate="30/10m", subject_rate="10/15m")
@role_required(HOD, Role.ADMIN)
@step_up_required
def reset_code(request):
    """Look an account up by its ID, within the issuer's scope, and issue it a reset code."""
    form = ResetCodeLookupForm(request.POST or None)
    status = 200
    if request.method == "POST":
        if request.limited:
            form.add_error(None, _("Too many attempts. Please wait a few minutes and try again."))
            status = 429
        elif form.is_valid():
            account = registry_service.resettable_account(
                form.cleaned_data["registry_id"], request.user
            )
            if account is not None:
                return _issue_reset_code(request, account, reverse("accounts:reset_code"))
            form.add_error("registry_id", _("No account you may reset has this ID."))
            status = 404
    context = {"nav_items": user_nav_items(request.user, "reset_code"), "form": form}
    return render(request, "accounts/reset_code.html", context, status=status)

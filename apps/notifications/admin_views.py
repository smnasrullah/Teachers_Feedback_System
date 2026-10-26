"""The Admin's notification screens: message templates (with test send) and the delivery log."""

from django.contrib import messages as flash
from django.core.paginator import Paginator
from django.http import Http404
from django.shortcuts import redirect, render
from django.utils.translation import gettext as _
from django.views.decorators.http import require_GET, require_http_methods, require_POST
from django_ratelimit.decorators import ratelimit

from apps.core.permissions import Role, role_required
from apps.core.services.navigation import admin_nav_items
from apps.notifications.forms import SendTestForm, TemplateForm
from apps.notifications.models import DeliveryLog, Kind
from apps.notifications.senders import EMAIL, SMS
from apps.notifications.services import editor, messages

PAGE_SIZE = 50
TEST_RATE = "10/m"


def _kind(value: str) -> str:
    if value not in Kind.values:
        raise Http404
    return value


@require_GET
@role_required(Role.ADMIN)
def template_list(request):
    context = {
        "nav_items": admin_nav_items("notification-templates"),
        "kinds": [(kind, label, editor.row_for(kind) is not None) for kind, label in Kind.choices],
    }
    return render(request, "notifications/template_list.html", context)


@require_http_methods(["GET", "POST"])
@role_required(Role.ADMIN)
def template_edit(request, kind):
    kind = _kind(kind)
    form = TemplateForm(kind, request.POST or None, initial=editor.initial(kind))
    if request.method == "POST" and form.is_valid():
        editor.save(kind, form.cleaned_data, actor=request.user, request=request)
        flash.success(request, _("The template was saved."))
        return redirect("notifications:template_edit", kind=kind)
    context = {
        "nav_items": admin_nav_items("notification-templates"),
        "kind": kind,
        "label": Kind(kind).label,
        "form": form,
        "variables": [(name, messages.VARIABLE_HELP[name]) for name in messages.VARIABLES[kind]],
        "test_form": SendTestForm(initial={"language": request.user.language}),
    }
    return render(request, "notifications/template_edit.html", context)


@require_POST
@role_required(Role.ADMIN)
@ratelimit(key="user", rate=TEST_RATE, method="POST", block=False)
def template_test(request, kind):
    """Send a sample of the saved template to the Admin themself, quiet hours aside."""
    kind = _kind(kind)
    form = SendTestForm(request.POST)
    if request.limited:
        flash.error(request, _("Too many test messages. Wait a moment."))
    elif form.is_valid():
        channels = editor.send_test(kind, form.cleaned_data["language"], request.user)
        reached = [
            label
            for channel, label in ((EMAIL, _("e-mail")), (SMS, _("text message")))
            if channel in channels
        ]
        if reached:
            flash.success(
                request,
                _("A sample was sent to your notifications and by %(channels)s.")
                % {"channels": ", ".join(reached)},
            )
        else:
            flash.warning(
                request,
                _(
                    "A sample was sent to your notifications. "
                    "Add a contact e-mail to your profile to get it by e-mail too."
                ),
            )
    return redirect("notifications:template_edit", kind=kind)


@require_GET
@role_required(Role.ADMIN)
def delivery_log(request):
    entries = DeliveryLog.objects.select_related("user")
    page = Paginator(entries, PAGE_SIZE).get_page(request.GET.get("page"))
    context = {"nav_items": admin_nav_items("delivery-log"), "page_obj": page}
    return render(request, "notifications/delivery_log.html", context)

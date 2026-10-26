"""The bell in the page header: unread badge, recent list, and marking notices read (HTMX)."""

from django.http import Http404
from django.shortcuts import redirect, render
from django.views.decorators.http import require_GET, require_POST

from apps.core.permissions import HOD, Role, role_required
from apps.notifications.services import inbox

SIGNED_IN = (Role.STUDENT, Role.TEACHER, Role.ADMIN, HOD)


def _list(request):
    context = {
        "entries": inbox.recent(request.user),
        "unread_count": inbox.unread_count(request.user),
    }
    return render(request, "notifications/_list.html", context)


@require_GET
@role_required(*SIGNED_IN)
def badge(request):
    return render(
        request, "notifications/_badge.html", {"unread_count": inbox.unread_count(request.user)}
    )


@require_GET
@role_required(*SIGNED_IN)
def bell_list(request):
    return _list(request)


@require_POST
@role_required(*SIGNED_IN)
def read_all(request):
    inbox.mark_all_read(request.user)
    return _list(request)


@require_POST
@role_required(*SIGNED_IN)
def open_notice(request, pk):
    notice = inbox.mark_read(request.user, pk)
    if notice is None:
        raise Http404
    return redirect(notice.url or "/")

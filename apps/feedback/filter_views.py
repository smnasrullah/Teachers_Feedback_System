"""Admin screens for the comment filter: the word lists and the comments it flagged."""

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext as _
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from apps.core.permissions import Role, role_required
from apps.core.services.navigation import admin_nav_items
from apps.feedback.forms import FilterTermForm
from apps.feedback.models import Answer, FilterTerm, FilterTermKind
from apps.feedback.services import filter_terms

PAGE_SIZE = 50


def _page(request, template: str, nav: str, **context):
    return render(request, template, {"nav_items": admin_nav_items(nav), **context})


@require_http_methods(["GET", "POST"])
@role_required(Role.ADMIN)
def filter_terms_view(request):
    form = FilterTermForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            filter_terms.add_term(
                form.cleaned_data["term"],
                form.cleaned_data["kind"],
                actor=request.user,
                request=request,
            )
        except ValidationError as error:
            form.add_error("term", error)
        else:
            messages.success(request, _("The word was added."))
            return redirect("feedback:filter_terms")
    terms = FilterTerm.objects.all()
    lists = [
        (_("Blocked words"), terms.filter(kind=FilterTermKind.BLOCK)),
        (_("Allowed words"), terms.filter(kind=FilterTermKind.ALLOW)),
    ]
    return _page(request, "admin_panel/filter_terms.html", "filter-terms", form=form, lists=lists)


@require_POST
@role_required(Role.ADMIN)
def filter_term_delete(request, pk):
    term = get_object_or_404(FilterTerm, pk=pk)
    filter_terms.remove_term(term, actor=request.user, request=request)
    messages.success(request, _("The word was removed."))
    return redirect("feedback:filter_terms")


@require_GET
@role_required(Role.ADMIN)
def flagged_list(request):
    """The comments the filter cleaned, as stored. They are listed without course, round or
    time, so no comment can be tied to a small group of respondents."""
    flagged = Answer.objects.filter(flagged=True).select_related("question").order_by("id")
    page_obj = Paginator(flagged, PAGE_SIZE).get_page(request.GET.get("page"))
    return _page(request, "admin_panel/flagged_list.html", "flagged", page_obj=page_obj, query="")

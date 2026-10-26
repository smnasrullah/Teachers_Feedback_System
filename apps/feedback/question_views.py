"""Admin screens for the question bank: list, edit (versioned), duplicate, activate, reorder
and categories."""

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db.models import Q, QuerySet
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext as _
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from apps.core.permissions import Role, role_required
from apps.core.services.navigation import admin_nav_items
from apps.feedback.forms import CategoryForm, QuestionFilterForm, QuestionForm
from apps.feedback.models import Question, QuestionCategory
from apps.feedback.services import questions

PAGE_SIZE = 50
ORDER_FIELD = "order_"


def _page(request, template: str, nav: str, **context):
    return render(request, template, {"nav_items": admin_nav_items(nav), **context})


def _filtered(data) -> tuple[QuestionFilterForm, QuerySet]:
    form = QuestionFilterForm(data)
    records = Question.objects.select_related("category").order_by("order", "pk")
    if not form.is_valid():
        return form, records.none()
    term, cleaned = form.cleaned_data["q"].strip(), form.cleaned_data
    if term:
        records = records.filter(Q(text__icontains=term) | Q(text_bn__icontains=term))
    if cleaned["category"]:
        records = records.filter(category=cleaned["category"])
    for name in ("question_type", "applies_to"):
        if cleaned[name]:
            records = records.filter(**{name: cleaned[name]})
    if cleaned["active"]:
        records = records.filter(is_active=cleaned["active"] == "1")
    return form, records


@require_GET
@role_required(Role.ADMIN)
def question_list(request):
    form, records = _filtered(request.GET)
    page_obj = Paginator(records, PAGE_SIZE).get_page(request.GET.get("page"))
    params = request.GET.copy()
    params.pop("page", None)
    return _page(
        request,
        "admin_panel/question_list.html",
        "questions",
        filter_form=form,
        page_obj=page_obj,
        query=f"{params.urlencode()}&" if params else "",
    )


def _question_form(request, question=None):
    if request.method == "POST":
        form = QuestionForm(request.POST, instance=question)
        if form.is_valid():
            try:
                if question is None:
                    saved = questions.create_question(
                        form.cleaned_question(), actor=request.user, request=request
                    )
                else:
                    saved = questions.update_question(
                        question.pk, form.cleaned_question(), actor=request.user, request=request
                    )
            except ValidationError as error:
                form.add_error(None, error.messages)
            else:
                if question is not None and saved.pk != question.pk:
                    messages.success(
                        request,
                        _("The question has answers, so your changes were saved as version %(n)d.")
                        % {"n": saved.version},
                    )
                else:
                    messages.success(request, _("The question was saved."))
                return redirect("feedback:questions")
    else:
        form = QuestionForm(instance=question)
    return _page(
        request,
        "admin_panel/question_form.html",
        "questions",
        form=form,
        question=question,
        answered=question is not None and questions.has_answers(question),
        newer=getattr(question, "superseded_by", None) if question else None,
    )


@require_http_methods(["GET", "POST"])
@role_required(Role.ADMIN)
def question_create(request):
    return _question_form(request)


@require_http_methods(["GET", "POST"])
@role_required(Role.ADMIN)
def question_edit(request, pk):
    return _question_form(request, get_object_or_404(Question, pk=pk))


@require_POST
@role_required(Role.ADMIN)
def question_duplicate(request, pk):
    get_object_or_404(Question, pk=pk)
    copy = questions.duplicate_question(pk, actor=request.user, request=request)
    messages.success(request, _("A copy was created. It is inactive until you activate it."))
    return redirect("feedback:question_edit", pk=copy.pk)


@require_POST
@role_required(Role.ADMIN)
def question_toggle(request, pk):
    question = get_object_or_404(Question, pk=pk)
    try:
        questions.set_active(pk, not question.is_active, actor=request.user, request=request)
    except ValidationError as error:
        messages.error(request, error.messages[0])
    else:
        messages.success(request, _("The question was updated."))
    return redirect("feedback:questions")


@require_http_methods(["GET", "POST"])
@role_required(Role.ADMIN)
def question_reorder(request):
    heads = Question.objects.filter(superseded_by__isnull=True).select_related("category")
    if request.method == "POST":
        known = set(heads.values_list("pk", flat=True))
        positions = {
            int(name.removeprefix(ORDER_FIELD)): int(value)
            for name, value in request.POST.items()
            if name.startswith(ORDER_FIELD)
            and name.removeprefix(ORDER_FIELD).isdecimal()
            and value.isdecimal()
            and int(name.removeprefix(ORDER_FIELD)) in known
        }
        questions.reorder(positions, actor=request.user, request=request)
        messages.success(request, _("The order was saved."))
        return redirect("feedback:questions")
    return _page(request, "admin_panel/question_reorder.html", "questions", questions=heads)


@require_http_methods(["GET", "POST"])
@role_required(Role.ADMIN)
def category_list(request):
    form = CategoryForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        questions.save_category(form, actor=request.user, request=request)
        messages.success(request, _("The category was saved."))
        return redirect("feedback:categories")
    return _page(
        request,
        "admin_panel/category_list.html",
        "categories",
        form=form,
        categories=QuestionCategory.objects.all(),
    )


@require_http_methods(["GET", "POST"])
@role_required(Role.ADMIN)
def category_edit(request, pk):
    category = get_object_or_404(QuestionCategory, pk=pk)
    form = CategoryForm(request.POST or None, instance=category)
    if request.method == "POST" and form.is_valid():
        questions.save_category(form, actor=request.user, request=request)
        messages.success(request, _("The category was saved."))
        return redirect("feedback:categories")
    return _page(
        request, "admin_panel/category_form.html", "categories", form=form, category=category
    )

"""Turn the four reports into ``Export`` tables.

Every figure is taken from the report services, which already hold back an open round and any
group below the response threshold; this module adds nothing of its own to what a viewer may
see, so a held-back figure is an empty cell with a note and never a number. Only per-course,
per-department and per-round figures appear. Comments come in the stable shuffled order of
``apps.analytics`` with no id, token, tag or time. The pending list is the one place with
student IDs, and ``StudentIdPolicy`` fills them in only for the Admin and the head of the
student's own department.
"""

from django.utils.translation import gettext as _

from apps.analytics import services as analytics
from apps.analytics.services import InsufficientData
from apps.core.services.localize import pick
from apps.feedback.models import SCALE_MAX, QuestionType
from apps.reports.services import department as department_service
from apps.reports.services import teacher, university
from apps.reports.services.exports.model import Bar, Chart, Export, Table

PERCENT = 100


def _name(obj) -> str:
    return pick(obj.name, obj.name_bn)


def _title(course) -> str:
    return pick(course.title, course.title_bn)


def _score_bars(pairs) -> tuple[Bar, ...]:
    return tuple(Bar(label, score, score / SCALE_MAX * PERCENT) for label, score in pairs)


def _trend_table(config) -> Table | None:
    if not config:
        return None
    data = config["datasets"][0]["data"]
    return Table(
        _("Average by round"),
        (_("Round"), _("Average rating")),
        tuple(zip(config["labels"], data, strict=True)),
    )


def _rate_cells(rate) -> tuple:
    """Submitted, enrolled and percent of a response rate; empty when it is held back."""
    if rate is None or isinstance(rate, InsufficientData):
        return (None, None, None)
    return (rate.submitted, rate.enrolled, round(rate.percent, 1))


def _tables(*tables) -> tuple[Table, ...]:
    return tuple(table for table in tables if table is not None)


# --- teacher course report ---------------------------------------------------------------------


def teacher_course(offering, window, viewer, now) -> Export:
    report = teacher.build_report(offering, window, viewer, now, everything=True)
    summary, course = report.summary, offering.course
    submitted, enrolled, percent = _rate_cells(summary.rate)
    facts = (
        (_("Course code"), course.code),
        (_("Course title"), _title(course)),
        (_("Section"), offering.section),
        (_("Teacher"), offering.teacher.registry.full_name),
        (_("Semester"), offering.semester.name),
        (_("Round"), window.name),
        (_("Overall average"), summary.average),
        (_("Responses"), submitted),
        (_("Enrolled students"), enrolled),
        (_("Response rate (%)"), percent),
        (_("Department average"), report.department_average),
        (_("Action taken"), report.note.text if report.note else None),
    )
    export = Export(
        kind="course",
        name=f"{course.code}-{offering.section or 'all'}-{window.name}",
        title=_("Course report"),
        subtitle=f"{course.code} · {_title(course)} · {offering.semester.name} · {window.name}",
        tables=(Table(_("Summary"), (_("Field"), _("Value")), facts),),
        notices=() if summary.rate else (str(summary.notice),),
        audit={"report": "course", "offering_id": offering.pk, "window_id": window.pk},
    )
    return _with_results(export, report) if summary.rate else export


def _with_results(export: Export, report) -> Export:
    rated, answers, comments, charts = [], [], [], []
    notices = list(export.notices)
    for block in report.blocks:
        question = block.question
        text = pick(question.text, question.text_bn)
        if block.kind == QuestionType.TEXT:
            if block.panel.notice:
                notices.append(f"{block.number}. {text}: {block.panel.notice}")
            comments.extend((block.number, text, comment.text) for comment in block.panel.comments)
            continue
        category = _name(question.category) if question.category else None
        rated.append(
            (
                block.number,
                category,
                text,
                question.get_question_type_display(),
                block.count or None,
                block.average,
                str(block.notice) or None,
            )
        )
        if block.rows:
            answers.extend(
                (block.number, text, row.label, row.count, round(row.percent, 1))
                for row in block.rows
            )
            bars = tuple(Bar(row.label, row.count, row.percent) for row in block.rows)
            charts.append(
                Chart(f"{block.number}. {text}", bars, stars=block.kind in analytics.RATED_TYPES)
            )
    if report.categories:
        charts.append(
            Chart(
                _("Scores by category"),
                _score_bars((row.name, row.score) for row in report.categories),
                scores=True,
            )
        )
    tables = _tables(
        *export.tables,
        Table(
            _("Questions"),
            (
                _("No."),
                _("Category"),
                _("Question"),
                _("Type"),
                _("Responses"),
                _("Average"),
                _("Note"),
            ),
            tuple(rated),
        ),
        Table(
            _("Answers"),
            (_("No."), _("Question"), _("Answer"), _("Responses"), _("Share (%)")),
            tuple(answers),
        )
        if answers
        else None,
        Table(
            _("Categories"),
            (_("Category"), _("Score"), _("Department average")),
            tuple((row.name, row.score, row.department) for row in report.categories),
        )
        if report.categories
        else None,
        _trend_table(report.trend),
        Table(_("Comments"), (_("No."), _("Question"), _("Comment")), tuple(comments))
        if comments
        else None,
    )
    return Export(
        export.kind,
        export.name,
        export.title,
        export.subtitle,
        tables,
        tuple(charts),
        tuple(notices),
        export.audit,
    )


# --- head of department report -----------------------------------------------------------------


def department_report(department, window, viewer, now, threshold) -> Export:
    overview = department_service.build_overview(department, window, viewer, now, threshold)
    average = None if isinstance(overview.average, InsufficientData) else overview.average.average
    facts = (
        (_("Department"), _name(department)),
        (_("Semester"), window.semester.name),
        (_("Round"), window.name),
        (_("Courses"), overview.offerings),
        (_("Teachers"), overview.teachers),
        (_("Responses"), _rate_cells(overview.rate)[0]),
        (_("Enrolled students"), _rate_cells(overview.rate)[1]),
        (_("Response rate (%)"), _rate_cells(overview.rate)[2]),
        (_("Department average"), average),
        (_("Alert threshold"), threshold),
    )
    courses = tuple(
        (
            row.rank,
            row.offering.course.code,
            _title(row.offering.course),
            row.offering.section,
            row.offering.teacher.registry.full_name,
            row.summary.average,
            *_rate_cells(row.summary.rate),
            (_("Yes") if row.low else _("No")) if row.rank is not None else None,
            _("Yes") if row.note else _("No"),
            str(row.summary.notice) or None,
        )
        for row in overview.rows
    )
    heat = overview.heatmap
    heat_table = (
        Table(
            _("Categories by course"),
            (_("Course code"), _("Section"), *heat.categories),
            tuple(
                (
                    row.summary.offering.course.code,
                    row.summary.offering.section,
                    *(cell.score if cell else None for cell in row.cells),
                )
                for row in heat.rows
            ),
        )
        if heat.rows
        else None
    )
    ranked = [row for row in overview.rows if row.rank is not None]
    charts = (
        Chart(
            _("Average rating by course"),
            _score_bars(
                (f"{row.offering.course.code} {row.offering.section}".strip(), row.summary.average)
                for row in ranked
            ),
            scores=True,
        ),
    )
    return Export(
        kind="department",
        name=f"{department.code}-{window.name}",
        title=_("Department report"),
        subtitle=f"{_name(department)} · {window.semester.name} · {window.name}",
        tables=_tables(
            Table(_("Summary"), (_("Field"), _("Value")), facts),
            Table(
                _("Courses"),
                (
                    _("Rank"),
                    _("Course code"),
                    _("Course title"),
                    _("Section"),
                    _("Teacher"),
                    _("Average"),
                    _("Responses"),
                    _("Enrolled students"),
                    _("Response rate (%)"),
                    _("Below threshold"),
                    _("Action note written"),
                    _("Note"),
                ),
                courses,
            ),
            heat_table,
            _trend_table(overview.trend),
        ),
        charts=charts if ranked else (),
        audit={"report": "department", "window_id": window.pk, "threshold": threshold},
    )


# --- university report -------------------------------------------------------------------------


def _ranking_rows(summaries) -> tuple[tuple, ...]:
    return tuple(
        (
            index,
            s.offering.course.code,
            _title(s.offering.course),
            s.offering.section,
            s.offering.course.department.code,
            s.offering.teacher.registry.full_name,
            s.average,
        )
        for index, s in enumerate(summaries, start=1)
    )


def university_report(filters, viewer, now) -> Export:
    report = university.build(filters, viewer, now)
    window = report.window
    facts = (
        (_("Semester"), window.semester.name),
        (_("Round"), window.name),
        (_("Department"), _name(filters.department) if filters.department else _("All")),
        (_("Level/term"), _name(filters.level_term) if filters.level_term else _("All")),
        (_("Courses"), report.courses),
        (_("Responses"), _rate_cells(report.rate)[0]),
        (_("Enrolled students"), _rate_cells(report.rate)[1]),
        (_("Response rate (%)"), _rate_cells(report.rate)[2]),
    )
    ranking_headers = (
        _("Rank"),
        _("Course code"),
        _("Course title"),
        _("Section"),
        _("Department"),
        _("Teacher"),
        _("Average"),
    )
    distribution = report.distribution
    shown = not isinstance(distribution, InsufficientData) and any(b.count for b in distribution)
    charts = []
    if shown:
        bars = tuple(Bar(str(b.value), b.count, b.percent) for b in distribution)
        charts.append(Chart(_("Share of answers (%)"), bars, stars=True))
    scored = [row for row in report.departments if row.average is not None]
    if scored:
        charts.append(
            Chart(
                _("Average rating by department"),
                _score_bars((row.department.code, row.average) for row in scored),
                scores=True,
            )
        )
    tables = _tables(
        Table(_("Summary"), (_("Field"), _("Value")), facts),
        Table(
            _("Departments"),
            (
                _("Department"),
                _("Courses"),
                _("Responses"),
                _("Enrolled students"),
                _("Response rate (%)"),
                _("Average"),
            ),
            tuple(
                (_name(row.department), row.courses, *_rate_cells(row.rate), row.average)
                for row in report.departments
            ),
        ),
        Table(_("Best rated courses"), ranking_headers, _ranking_rows(report.top))
        if report.top
        else None,
        Table(_("Lowest rated courses"), ranking_headers, _ranking_rows(report.bottom))
        if report.bottom
        else None,
        Table(
            _("Answers"),
            (_("Rating"), _("Responses"), _("Share (%)")),
            tuple((b.value, b.count, round(b.percent, 1)) for b in distribution),
        )
        if shown
        else None,
        _trend_table(report.trend),
    )
    return Export(
        kind="university",
        name=f"university-{window.name}",
        title=_("University report"),
        subtitle=f"{window.semester.name} · {window.name}",
        tables=tables,
        charts=tuple(charts),
        notices=() if report.released else (_("Results are released after the round closes."),),
        audit={
            "report": "university",
            "window_id": window.pk,
            "department_id": filters.department.pk if filters.department else None,
            "level_term_id": filters.level_term.pk if filters.level_term else None,
        },
    )


# --- pending submissions -----------------------------------------------------------------------


def pending_submissions(department, window, viewer, offerings, level_term=None) -> Export:
    """Students still owing feedback. IDs come from ``StudentIdPolicy`` (the Admin, or the head
    of the student's own department); students of other departments are counted, not listed."""
    pending = department_service.pending_list(department, window, viewer, offerings, level_term)
    rows = tuple(
        (
            row.student.visible_student_id,
            row.offering.course.code,
            row.offering.section,
            _name(row.student.level_term),
        )
        for row in pending.rows
    )
    facts = (
        (_("Department"), _name(department)),
        (_("Semester"), window.semester.name),
        (_("Round"), window.name),
        (_("Level/term"), _name(level_term) if level_term else _("All")),
        (_("Courses"), len(offerings)),
        (_("Students pending"), len(rows)),
        (_("Students of other departments pending"), pending.others),
    )
    return Export(
        kind="pending",
        name=f"pending-{department.code}-{window.name}",
        title=_("Pending feedback"),
        subtitle=f"{_name(department)} · {window.semester.name} · {window.name}",
        tables=(
            Table(_("Summary"), (_("Field"), _("Value")), facts),
            Table(
                _("Pending students"),
                (_("Student ID"), _("Course code"), _("Section"), _("Level/term")),
                rows,
            ),
        ),
        audit={
            "report": "pending",
            "window_id": window.pk,
            "rows": len(rows),
            "level_term_id": level_term.pk if level_term else None,
        },
    )

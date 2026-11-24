"""Why a student or teacher sees (or does not see) a course or a round: an operator checklist.

It reads the same services the pages read (``courses_for_student``, ``offerings_for_teacher``,
``FeedbackWindow.covers``), so what it reports is what the person's dashboard shows. It names
only registry rows, course codes, rounds and counts: never a password, an authenticator secret,
an activation code or anything a student wrote.
"""

from dataclasses import dataclass

from django.utils import timezone
from django.utils.translation import gettext as _

from apps.academics.models import CourseOffering
from apps.academics.services import semesters
from apps.academics.services.teaching import offerings_for_teacher
from apps.accounts.models import AcademicStatus, IdRegistry, IdType, RegistryStatus, registry_index
from apps.accounts.services.identifiers import normalize_registry_id
from apps.core.permissions import primary_role
from apps.enrollment.models import Enrollment
from apps.enrollment.services import enrollments
from apps.enrollment.services.courses import courses_for_student
from apps.feedback.models import FeedbackWindow, SubmissionReceipt


@dataclass(frozen=True)
class Check:
    ok: bool
    label: str
    detail: str = ""


def _codes(offerings) -> str:
    return ", ".join(offering.course.code for offering in offerings) or "-"


def _account(registry: IdRegistry) -> list[Check]:
    account = registry.claimed_by
    checks = [
        Check(
            registry.status != RegistryStatus.REVOKED,
            _("Registry entry"),
            f"{registry.get_id_type_display()} | {registry.get_status_display()} | "
            f"{registry.department.code}",
        )
    ]
    if account is None:
        checks.append(Check(False, _("Account"), _("Not signed up yet: nothing can be seen.")))
    else:
        role = primary_role(account) or "-"
        checks.append(
            Check(
                account.is_active,
                _("Account"),
                f"{account.username} | {role}"
                + ("" if account.is_active else f" | {_('inactive')}"),
            )
        )
    return checks


def _semester(now) -> tuple[list[Check], object]:
    semester = semesters.current_semester(timezone.localdate(now, timezone.get_default_timezone()))
    if semester is None:
        return [
            Check(False, _("Current semester"), _("None runs today: no courses are shown."))
        ], None
    dates = f"{semester.start_date.isoformat()} .. {semester.end_date.isoformat()}"
    return [Check(True, _("Current semester"), f"{semester.name} ({dates})")], semester


def _rounds(semester, offerings, now, receipts) -> list[Check]:
    windows = FeedbackWindow.objects.filter(semester=semester).prefetch_related(
        "departments", "level_terms"
    )
    checks = []
    for window in windows:
        covered = [offering for offering in offerings if window.covers(offering)]
        status = window.status(now) if window.is_active else _("inactive")
        detail = f"{window.name} | {status} | {_('covers')}: {_codes(covered)}"
        if receipts is not None:
            done = sum((offering.pk, window.pk) in receipts for offering in covered)
            detail += f" | {_('submitted')}: {done}/{len(covered)}"
        checks.append(Check(window.is_active and bool(covered), _("Round"), detail))
    if not checks:
        checks.append(Check(False, _("Round"), _("No round in this semester yet.")))
    return checks


def _student(registry, now) -> list[Check]:
    profile = registry.student_profile
    checks = [
        Check(
            profile.academic_status == AcademicStatus.ACTIVE,
            _("Student profile"),
            f"{profile.program} | {profile.level_term.name} | "
            f"{_('section')} {profile.section or '-'} | {profile.get_academic_status_display()}",
        )
    ]
    more, semester = _semester(now)
    checks += more
    if semester is None:
        return checks
    courses = courses_for_student(profile, semester)
    checks.append(Check(bool(courses), _("Courses on the dashboard"), _codes(courses)))
    elsewhere = Enrollment.objects.filter(student_profile=profile).exclude(
        offering__semester=semester
    )
    if elsewhere.exists():
        checks.append(
            Check(True, _("Enrollments in other semesters (not shown)"), str(elsewhere.count()))
        )
    missing = enrollments.plan_rule(
        type(profile).objects.filter(pk=profile.pk),
        CourseOffering.objects.filter(semester=semester),
    ).new
    if missing:
        codes = _codes(
            CourseOffering.objects.filter(pk__in=[item.offering_id for item in missing])
            .select_related("course")
            .order_by("course__code")
        )
        checks.append(Check(False, _("Level/term courses not enrolled"), codes))
    receipts = set(
        SubmissionReceipt.objects.filter(student_profile=profile).values_list(
            "offering_id", "window_id"
        )
    )
    return checks + _rounds(semester, courses, now, receipts)


def _teacher(registry, now) -> list[Check]:
    profile = registry.teacher_profile
    head = profile.hod_department.code if profile.is_hod else "-"
    checks = [Check(True, _("Head of department"), head)]
    more, semester = _semester(now)
    checks += more
    if semester is None:
        return checks
    offerings = offerings_for_teacher(profile, semester)
    checks.append(Check(bool(offerings), _("Courses on the dashboard"), _codes(offerings)))
    elsewhere = CourseOffering.objects.filter(teacher=profile).exclude(semester=semester)
    if elsewhere.exists():
        checks.append(
            Check(True, _("Offerings in other semesters (not shown)"), str(elsewhere.count()))
        )
    return checks + _rounds(semester, offerings, now, None)


def explain(external_id: str, now=None) -> list[list[Check]]:
    """One checklist per registry entry with this ID (a student and a teacher may share one)."""
    now = now or timezone.now()
    rows = IdRegistry.objects.select_related("claimed_by", "department").filter(
        external_id_index=registry_index(normalize_registry_id(external_id))
    )
    reports = []
    for registry in rows.order_by("id_type"):
        checks = _account(registry)
        checks += (
            _student(registry, now)
            if registry.id_type == IdType.STUDENT
            else _teacher(registry, now)
        )
        reports.append(checks)
    return reports

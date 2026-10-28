"""Semesters: which one is running, the date rules an admin's change must keep, audited saves.

The status of a semester is always computed from today's date in the university's time zone
(``Semester.status``); nothing stores or flips a "current" flag. Two semesters never share a
day, so at most one is ongoing. Offerings and enrolments carry no dates of their own (they are
inside their semester by definition), so the feedback rounds are what a date change can strand.
"""

from datetime import date, datetime, time, timedelta

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q
from django.utils import formats, timezone
from django.utils.translation import gettext as _

from apps.academics.models import Season, Semester
from apps.auditlog.services import audit
from apps.core.services.localize import localize_digits
from apps.feedback.models import FeedbackWindow

LAST_WINTER_START_MONTH = 6  # with no semester yet, January to June suggests a Winter one


def today() -> date:
    """Today in the university's time zone (``TIME_ZONE``, Asia/Dhaka)."""
    return timezone.localdate(timezone.now(), timezone.get_default_timezone())


def current_semester(on: date | None = None) -> Semester | None:
    """The semester running on ``on`` (default: today), or ``None`` between semesters."""
    return Semester.objects.ongoing(on or today()).order_by("-start_date").first()


def ongoing():
    """Today's semester as a queryset, for lookups such as ``offering__semester__in``."""
    return Semester.objects.ongoing(today())


def following(season: str, year: int) -> tuple[str, int]:
    """The next semester in turn: Summer Y -> Winter Y+1, Winter Y -> Summer Y."""
    return (Season.SUMMER, year) if season == Season.WINTER else (Season.WINTER, year + 1)


def suggest_next() -> dict:
    """Season and year for the "create next semester" form; the admin still types the dates."""
    latest = Semester.objects.order_by("-start_date").first()
    if latest is not None:
        season, year = following(latest.season, latest.year)
    else:
        now = today()
        winter = now.month <= LAST_WINTER_START_MONTH
        season, year = (Season.WINTER if winter else Season.SUMMER), now.year
    return {"season": season, "year": year}


def short_date(day: date) -> str:
    """ "30 Jan 2027" ("৩০ জানু ২০২৭" in Bangla)."""
    return localize_digits(formats.date_format(day, "j M Y"))


def ends_at(semester: Semester) -> datetime:
    """The instant the semester's last day ends, in local time."""
    return _day_bounds(semester.start_date, semester.end_date)[1]


def _day_bounds(start: date, end: date) -> tuple[datetime, datetime]:
    """The first instant of ``start`` and the instant after ``end`` ends, in local time."""
    zone = timezone.get_default_timezone()
    return (
        datetime.combine(start, time.min, tzinfo=zone),
        datetime.combine(end + timedelta(days=1), time.min, tzinfo=zone),
    )


def overlapping(start: date, end: date, *, exclude_pk=None) -> list[Semester]:
    """Semesters sharing at least one day with ``start``..``end`` (both days included)."""
    return list(
        Semester.objects.filter(start_date__lte=end, end_date__gte=start).exclude(pk=exclude_pk)
    )


def stranded_rounds(semester: Semester, start: date, end: date) -> list[FeedbackWindow]:
    """Rounds of ``semester`` that would open before ``start`` or close after ``end``."""
    if semester.pk is None:
        return []
    begins, ends = _day_bounds(start, end)
    return list(
        FeedbackWindow.objects.filter(semester=semester)
        .filter(Q(opens_at__lt=begins) | Q(closes_at__gt=ends))
        .order_by("opens_at")
    )


def validate_dates(semester: Semester, start: date, end: date) -> None:
    """Raise a ``ValidationError`` naming what blocks ``start``..``end`` for ``semester``."""
    errors = []
    clashes = overlapping(start, end, exclude_pk=semester.pk)
    if clashes:
        errors.append(
            ValidationError(
                _("These dates overlap %(names)s (%(start)s to %(end)s)."),
                code="overlap",
                params={
                    "names": clashes[0].name,
                    "start": short_date(clashes[0].start_date),
                    "end": short_date(clashes[0].end_date),
                },
            )
        )
    for window in stranded_rounds(semester, start, end):
        zone = timezone.get_default_timezone()
        errors.append(
            ValidationError(
                _(
                    "The feedback round “%(round)s” runs from %(opens)s to %(closes)s, which "
                    "would fall outside the semester. Change the round first or keep these "
                    "dates around it."
                ),
                code="round_outside",
                params={
                    "round": window.name,
                    "opens": short_date(timezone.localtime(window.opens_at, zone).date()),
                    "closes": short_date(timezone.localtime(window.closes_at, zone).date()),
                },
            )
        )
    if errors:
        raise ValidationError(errors)


def _audit_dates(semester: Semester, old: dict | None) -> dict:
    new = {
        "season": semester.season,
        "year": semester.year,
        "start_date": semester.start_date.isoformat(),
        "end_date": semester.end_date.isoformat(),
    }
    if old is None:
        return new
    return {key: [old[key], value] for key, value in new.items() if old[key] != value}


@transaction.atomic
def save(form, *, actor, request=None) -> Semester:
    """Save a validated ``SemesterForm`` and audit it with every old -> new value.

    All semester rows are locked while the date rules are checked again, so two admins cannot
    save overlapping semesters at the same moment. Raises ``ValidationError`` when blocked.
    """
    created = form.instance.pk is None
    if not created and not form.has_changed():
        return form.instance
    locked = {row.pk: row for row in Semester.objects.select_for_update().order_by("pk")}
    stored = locked.get(form.instance.pk)
    old = None if stored is None else _audit_dates(stored, None)
    semester = form.save(commit=False)
    validate_dates(semester, semester.start_date, semester.end_date)
    semester.save()
    audit.record(
        f"academics.semester_{'created' if created else 'updated'}",
        request=request,
        actor=actor,
        target=semester,
        metadata={"entity": "semesters", **_audit_dates(semester, old)},
    )
    return semester

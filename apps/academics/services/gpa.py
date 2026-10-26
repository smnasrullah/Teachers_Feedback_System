"""Credit-weighted GPA arithmetic over published results.

The term GPA counts every attempt made in that semester. The CGPA counts each course once,
through the attempt the retake policy picks (the latest by default, or the best).
GPAs are rounded half-up to two decimals, the precision they are published and compared at.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from apps.academics.models import Result, RetakePolicy, Semester

PLACES = Decimal("0.01")


@dataclass(frozen=True)
class Attempt:
    """One published result: a course taken once, in one semester."""

    course_id: int
    semester_id: int
    semester_start: date
    enrollment_id: int
    credit: Decimal
    points: Decimal
    passed: bool

    @property
    def sequence(self) -> tuple:
        return (self.semester_start, self.semester_id, self.enrollment_id)


def weighted(attempts: Iterable[Attempt]) -> Decimal | None:
    """Sum of credit x points over the sum of credits; ``None`` when there are no credits."""
    attempts = list(attempts)
    credits = sum((attempt.credit for attempt in attempts), Decimal(0))
    if not credits:
        return None
    total = sum((attempt.credit * attempt.points for attempt in attempts), Decimal(0))
    return (total / credits).quantize(PLACES, rounding=ROUND_HALF_UP)


def counting(attempts: Iterable[Attempt], policy: str) -> dict[int, Attempt]:
    """The attempt that counts for each course: the latest one, or the best (a tie goes to
    the later attempt)."""
    chosen: dict[int, Attempt] = {}
    for attempt in sorted(attempts, key=lambda item: item.sequence):
        current = chosen.get(attempt.course_id)
        if current is None or policy == RetakePolicy.LATEST or attempt.points >= current.points:
            chosen[attempt.course_id] = attempt
    return chosen


def term_gpa(attempts: Iterable[Attempt], semester_id: int) -> Decimal | None:
    return weighted(attempt for attempt in attempts if attempt.semester_id == semester_id)


def cgpa(attempts: Iterable[Attempt], policy: str) -> Decimal | None:
    return weighted(counting(attempts, policy).values())


def failed_courses(attempts: Iterable[Attempt], policy: str) -> tuple[int, ...]:
    """Courses whose counting attempt is a failing grade: they still have to be retaken."""
    return tuple(
        sorted(
            course for course, attempt in counting(attempts, policy).items() if not attempt.passed
        )
    )


def load_attempts(student_ids: Iterable[int], up_to: Semester) -> dict[int, list[Attempt]]:
    """Published attempts of each student in ``up_to`` and the semesters that started before."""
    rows = Result.objects.filter(
        published=True,
        enrollment__student_profile_id__in=list(student_ids),
        enrollment__offering__semester__start_date__lte=up_to.start_date,
    ).values_list(
        "enrollment__student_profile_id",
        "enrollment__offering__course_id",
        "enrollment__offering__semester_id",
        "enrollment__offering__semester__start_date",
        "enrollment_id",
        "enrollment__offering__course__credit",
        "points",
        "grade__is_pass",
    )
    found: dict[int, list[Attempt]] = {}
    for student, *fields in rows:
        found.setdefault(student, []).append(Attempt(*fields))
    return found

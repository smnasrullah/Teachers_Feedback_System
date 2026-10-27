"""Demo academic data: departments down to offerings, enrolments, published results, promotion.

Structure rows are looked up by their natural key first, so a database that already has a
``CSE`` department or a "Level 2 Term 1" simply reuses it. Grades are saved and promotion is
applied through the real services (so they are audited), and a step that was done before is
skipped, which keeps a second run from changing anything.
"""

import random
from dataclasses import dataclass, replace
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.utils.translation import gettext as _

from apps.academics.models import (
    Batch,
    Course,
    CourseOffering,
    CourseType,
    Department,
    GradeScale,
    LevelTerm,
    Program,
    Result,
    Semester,
)
from apps.academics.services import promotion, results, semesters
from apps.core.services.demo import constants as c
from apps.enrollment.models import Enrollment


@dataclass(frozen=True)
class Structure:
    departments: dict[str, Department]
    programs: dict[str, Program]
    batches: dict[str, Batch]
    level_terms: dict[str, LevelTerm]
    semesters: dict[tuple[str, int], Semester]
    courses: dict[str, Course]


def _level_terms() -> dict[str, LevelTerm]:
    taken = set(LevelTerm.objects.values_list("order", flat=True))
    found = {}
    for name, name_bn, order in c.LEVEL_TERMS:
        level_term = LevelTerm.objects.filter(name=name).first()
        if level_term is None:
            if order in taken:  # the owner's own scheme uses this position: go after it
                order = max(taken) + 1
            taken.add(order)
            level_term = LevelTerm.objects.create(name=name, name_bn=name_bn, order=order)
        found[name] = level_term
    return found


def _semesters() -> dict[tuple[str, int], Semester]:
    """Winter 2026 and Summer 2026. An existing one is reused as it is (its dates may have been
    corrected by the admin); a new one must not overlap a semester of the owner's own."""
    found = {}
    for (season, year), (start, end) in c.SEMESTER_DATES.items():
        semester = Semester.objects.filter(season=season, year=year).first()
        if semester is None:
            semester = Semester(season=season, year=year, start_date=start, end_date=end)
            semesters.validate_dates(semester, start, end)
            semester.save()
        found[season, year] = semester
    return found


def ensure_structure() -> Structure:
    """Departments, programs, batches, levels/terms, semesters and courses (created if missing)."""
    semesters = _semesters()
    departments, programs, batches = {}, {}, {}
    for code, name, name_bn in c.DEPARTMENTS:
        department = Department.objects.get_or_create(
            code=code, defaults={"name": name, "name_bn": name_bn}
        )[0]
        name_en, name_bn_program = c.PROGRAM_NAMES[code]
        programs[code] = Program.objects.get_or_create(
            department=department,
            code=c.PROGRAM_CODE,
            defaults={"name": name_en, "name_bn": name_bn_program},
        )[0]
        batches[code] = Batch.objects.get_or_create(program=programs[code], name=c.BATCH_NAME)[0]
        departments[code] = department
    level_terms = _level_terms()
    courses = {
        spec.code: Course.objects.get_or_create(
            department=departments[spec.department],
            code=spec.code,
            defaults={
                "title": spec.title,
                "title_bn": spec.title_bn,
                "credit": Decimal(spec.credit),
                "course_type": spec.kind,
                "program": programs[spec.department],
                "level_term": level_terms[spec.level],
            },
        )[0]
        for spec in c.COURSES
    }
    return Structure(departments, programs, batches, level_terms, semesters, courses)


def ensure_offerings(structure: Structure, teachers: dict) -> dict[tuple, CourseOffering]:
    """Every offering as ``((season, year), course code) -> offering``."""
    offerings = {}
    for semester, teaching in ((c.SUMMER, c.SUMMER_TEACHING), (c.WINTER, c.WINTER_TEACHING)):
        for code, teacher in teaching.items():
            offerings[semester, code] = CourseOffering.objects.get_or_create(
                course=structure.courses[code],
                semester=structure.semesters[semester],
                section="",
                defaults={"teacher": teachers[teacher]},
            )[0]
    return offerings


def enroll_winter(offerings, cse, eee) -> None:
    """The previous semester's classes: all CSE students in the four Level 1 Term 2 courses,
    all EEE students in the two EEE courses."""
    rows = [
        Enrollment(student_profile=student, offering=offerings[c.WINTER, code])
        for students, codes in ((cse, c.WINTER_CSE_COURSES), (eee, c.WINTER_EEE_COURSES))
        for student in students
        for code in codes
    ]
    Enrollment.objects.bulk_create(rows, ignore_conflicts=True)


def _grade_letters(cse, eee, offering) -> dict[int, str]:
    """The letter each enrolled student earns in ``offering`` (the same plan on every run)."""
    code = offering.course.code
    letters = {}
    if code.startswith(f"{c.CSE}-"):
        names, weights = zip(*c.CSE_GRADE_WEIGHTS, strict=True)
        for index, student in enumerate(cse):
            rng = random.Random(f"grade:{index}:{code}")  # noqa: S311 - demo data, not security
            letters[student.pk] = rng.choices(names, weights)[0]
    else:
        column = 0 if offering.course.course_type == CourseType.THEORY else 1
        for index, student in enumerate(eee):
            letters[student.pk] = c.EEE_GRADES[index][column]
    return letters


def publish_results(offerings, cse, eee, actor) -> None:
    """Grade and publish each previous-semester offering that has no published result yet."""
    scale = {grade.letter: grade for grade in GradeScale.objects.all()}
    for code in (*c.WINTER_CSE_COURSES, *c.WINTER_EEE_COURSES):
        offering = offerings[c.WINTER, code]
        if Result.objects.filter(enrollment__offering=offering, published=True).exists():
            continue
        letters = _grade_letters(cse, eee, offering)
        missing = sorted(set(letters.values()) - set(scale))
        if missing:
            raise ValidationError(
                _("The grade scale has no grade %(letters)s, which the demo results use.")
                % {"letters": ", ".join(missing)}
            )
        grades = {
            enrollment.pk: scale[letters[enrollment.student_profile_id]]
            for enrollment in results.grade_sheet(offering)
        }
        results.save_grades(offering, grades, publish=True, actor=actor)


def promote_cse(semester: Semester, cse, actor) -> int:
    """Apply the promotion of the CSE students (the EEE ones stay in the preview as examples)."""
    planned = promotion.preview(semester)
    cohort = {student.pk for student in cse}
    mine = replace(
        planned,
        decisions=tuple(d for d in planned.decisions if d.student_profile_id in cohort),
    )
    return promotion.apply(mine, actor=actor)

"""Bulk CSV import: upload -> validate -> preview with row errors -> apply atomically.

``run()`` is the only entry point and one code path serves the preview (``apply=False``:
everything is written inside a transaction that is then rolled back, so conflicts the
database alone can see still show up) and the real import. Either every row is written or
none is. Imports only ever create records; they never change or delete existing ones.

Audit events carry counts only: never an ID, a name or an activation code.
"""

import csv
import io
from dataclasses import dataclass, field
from datetime import timedelta
from decimal import Decimal, InvalidOperation
from functools import cached_property

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy

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
from apps.accounts.models import (
    IdRegistry,
    IdType,
    RegistryStatus,
    StudentProfile,
    TeacherProfile,
    registry_index,
)
from apps.accounts.services import activation
from apps.accounts.services.identifiers import clean_registry_id
from apps.accounts.services.registry import IssuedCode
from apps.auditlog.services import audit
from apps.core.csv_safe import clean_cell
from apps.enrollment.models import Enrollment, EnrollmentStatus

MAX_BYTES = 5 * 1024 * 1024
MAX_ROWS = 10_000
MAX_REPORTED_ERRORS = 200
BULK_BATCH = 1000
DEFAULT_CODE_VALID_DAYS = 14
TRUE_WORDS = frozenset({"1", "yes", "y", "true"})
FALSE_WORDS = frozenset({"", "0", "no", "n", "false"})


class ImportRejected(ValidationError):
    """The file as a whole cannot be imported (size, encoding, header, row limit, a race)."""


class RowInvalid(Exception):
    """One row is wrong; ``column`` names the offending cell."""

    def __init__(self, column: str, message: str):
        super().__init__(message)
        self.column = column
        self.message = message


@dataclass(frozen=True)
class RowError:
    line: int
    column: str
    message: str


@dataclass
class ImportResult:
    kind: str
    total: int
    created: int = 0
    sanitized: int = 0
    error_count: int = 0
    errors: list[RowError] = field(default_factory=list)
    issued: list[IssuedCode] = field(default_factory=list)
    applied: bool = False

    @property
    def ok(self) -> bool:
        return self.error_count == 0


def _shown(value: str) -> str:
    return value if len(value) <= 40 else value[:40] + "…"


def _text(row: dict, column: str, *, max_length: int, required: bool = False) -> str:
    value = row.get(column, "")
    if required and not value:
        raise RowInvalid(column, _("This value is required."))
    if len(value) > max_length:
        raise RowInvalid(column, _("At most %(max)d characters are allowed.") % {"max": max_length})
    return value


def _flag(row: dict, column: str) -> bool:
    word = row.get(column, "").casefold()
    if word in TRUE_WORDS:
        return True
    if word in FALSE_WORDS:
        return False
    raise RowInvalid(column, _("Use yes or no."))


class _Lookups:
    """Reference data by natural key, each loaded once, on first use."""

    @cached_property
    def departments(self) -> dict[str, Department]:
        return {d.code.casefold(): d for d in Department.objects.all()}

    @cached_property
    def programs(self) -> dict[tuple[int, str], Program]:
        return {(p.department_id, p.code.casefold()): p for p in Program.objects.all()}

    @cached_property
    def level_terms(self) -> dict[str, list[LevelTerm]]:
        found: dict[str, list[LevelTerm]] = {}
        for level_term in LevelTerm.objects.all():
            found.setdefault(level_term.name.casefold(), []).append(level_term)
        return found

    @cached_property
    def batches(self) -> dict[tuple[int, str], Batch]:
        return {(b.program_id, b.name.casefold()): b for b in Batch.objects.all()}

    @cached_property
    def semesters(self) -> dict[str, Semester]:
        return {s.name.casefold(): s for s in Semester.objects.all()}

    @cached_property
    def courses(self) -> dict[tuple[int, str], Course]:
        return {(c.department_id, c.code.casefold()): c for c in Course.objects.all()}

    def department(self, row: dict, column: str = "department") -> Department:
        value = _text(row, column, max_length=16, required=True)
        try:
            return self.departments[value.casefold()]
        except KeyError:
            raise RowInvalid(
                column, _("Unknown department “%(value)s”.") % {"value": _shown(value)}
            ) from None

    def program(self, row: dict, department: Department) -> Program:
        value = _text(row, "program", max_length=16, required=True)
        try:
            return self.programs[(department.pk, value.casefold())]
        except KeyError:
            raise RowInvalid(
                "program",
                _("Unknown program “%(value)s” in this department.") % {"value": _shown(value)},
            ) from None

    def level_term(self, row: dict) -> LevelTerm:
        value = _text(row, "level_term", max_length=50, required=True)
        matches = self.level_terms.get(value.casefold(), [])
        if not matches:
            raise RowInvalid(
                "level_term", _("Unknown level/term “%(value)s”.") % {"value": _shown(value)}
            )
        if len(matches) > 1:
            raise RowInvalid(
                "level_term", _("More than one level/term is named “%(value)s”.") % {"value": value}
            )
        return matches[0]

    def batch(self, row: dict, program: Program) -> Batch | None:
        value = _text(row, "batch", max_length=50)
        if not value:
            return None
        try:
            return self.batches[(program.pk, value.casefold())]
        except KeyError:
            raise RowInvalid(
                "batch", _("Unknown batch “%(value)s” in this program.") % {"value": _shown(value)}
            ) from None

    def semester(self, row: dict) -> Semester:
        value = _text(row, "semester", max_length=50, required=True)
        try:
            return self.semesters[value.casefold()]
        except KeyError:
            raise RowInvalid(
                "semester", _("Unknown semester “%(value)s”.") % {"value": _shown(value)}
            ) from None

    def course(self, row: dict, department: Department) -> Course:
        value = _text(row, "course_code", max_length=20, required=True)
        try:
            return self.courses[(department.pk, value.casefold())]
        except KeyError:
            raise RowInvalid(
                "course_code",
                _("Unknown course “%(value)s” in this department.") % {"value": _shown(value)},
            ) from None


class Importer:
    """One kind of import: its CSV columns, per-row checks and bulk write."""

    key: str
    title: str
    summary: str
    required: tuple[str, ...]
    optional: tuple[str, ...] = ()
    sample: tuple[tuple[str, ...], ...]
    issues_codes = False

    def __init__(self, *, issue_codes: bool = False, valid_days: int = DEFAULT_CODE_VALID_DAYS):
        self.issue_codes = issue_codes and self.issues_codes
        self.valid_days = valid_days
        self.lookups = _Lookups()

    @property
    def columns(self) -> tuple[str, ...]:
        return self.required + self.optional

    def clean(self, row: dict):
        """The record for ``row`` (a model instance or plain value); raises ``RowInvalid``."""
        raise NotImplementedError

    def finish(self, records: list[tuple[int, object]]) -> list[RowError]:
        """Checks that need every record at once (for example against stored rows)."""
        return []

    def save(self, records: list, *, with_codes: bool) -> list[IssuedCode]:
        raise NotImplementedError


@dataclass(frozen=True)
class _RegistryRecord:
    external_id: str
    index: str
    full_name: str
    department: Department
    profile: dict


class _RegistryImporter(Importer):
    id_type: str
    id_column: str
    profile_model: type
    issues_codes = True

    def __init__(self, **options):
        super().__init__(**options)
        self._taken = set(
            IdRegistry.objects.filter(id_type=self.id_type).values_list(
                "external_id_index", flat=True
            )
        )

    def identity(self, row: dict) -> tuple[str, str, Department]:
        try:
            external_id = clean_registry_id(row[self.id_column])
        except ValidationError as error:
            raise RowInvalid(self.id_column, error.messages[0]) from None
        index = registry_index(external_id)
        if index in self._taken:
            raise RowInvalid(self.id_column, _("This ID is already registered."))
        self._taken.add(index)
        return external_id, index, self.lookups.department(row)

    def profile(self, row: dict, department: Department) -> dict:
        raise NotImplementedError

    def clean(self, row: dict) -> _RegistryRecord:
        external_id, index, department = self.identity(row)
        full_name = _text(row, "full_name", max_length=150)
        return _RegistryRecord(
            external_id, index, full_name, department, self.profile(row, department)
        )

    def save(self, records: list[_RegistryRecord], *, with_codes: bool) -> list[IssuedCode]:
        expires_at = timezone.now() + timedelta(days=self.valid_days)
        issued = []
        registries = []
        for record in records:
            registry = IdRegistry(
                id_type=self.id_type,
                external_id=record.external_id,
                external_id_index=record.index,
                full_name=record.full_name or None,
                department=record.department,
                status=RegistryStatus.UNCLAIMED,
            )
            if with_codes and self.issue_codes:
                code = activation.generate_code()
                registry.activation_code_hash = activation.hash_code(code)
                registry.activation_expires_at = expires_at
                issued.append(IssuedCode(registry, code))
            registries.append(registry)
        IdRegistry.objects.bulk_create(registries, batch_size=BULK_BATCH)
        self.profile_model.objects.bulk_create(
            [
                self.profile_model(registry=registry, **record.profile)
                for registry, record in zip(registries, records, strict=True)
            ],
            batch_size=BULK_BATCH,
        )
        return issued


class StudentImporter(_RegistryImporter):
    key = "students"
    title = gettext_lazy("Student IDs")
    summary = gettext_lazy(
        "Pre-registers students (registry entry and profile) so they can sign up and be enrolled."
    )
    id_type = IdType.STUDENT
    id_column = "student_id"
    profile_model = StudentProfile
    required = ("student_id", "department", "program", "level_term")
    optional = ("full_name", "batch", "section")
    sample = (
        ("2101001", "CSE", "BSC-CSE", "Level 1 Term 1", "Rahim Uddin", "2021", "A"),
        ("2101002", "CSE", "BSC-CSE", "Level 1 Term 1", "", "", ""),
    )

    def profile(self, row, department):
        program = self.lookups.program(row, department)
        return {
            "program": program,
            "batch": self.lookups.batch(row, program),
            "level_term": self.lookups.level_term(row),
            "section": _text(row, "section", max_length=16),
        }


class TeacherImporter(_RegistryImporter):
    key = "teachers"
    title = gettext_lazy("Teacher IDs")
    summary = gettext_lazy(
        "Pre-registers teachers (registry entry and profile) so they can sign up and be assigned."
    )
    id_type = IdType.TEACHER
    id_column = "teacher_id"
    profile_model = TeacherProfile
    required = ("teacher_id", "department")
    optional = ("full_name", "designation")
    sample = (("T0001", "CSE", "Karim Sir", "Lecturer"), ("T0002", "CSE", "", ""))

    def profile(self, row, department):
        return {"designation": _text(row, "designation", max_length=100)}


class CourseImporter(Importer):
    key = "courses"
    title = gettext_lazy("Courses")
    summary = gettext_lazy("Adds courses to the curriculum.")
    required = ("department", "code", "title", "credit", "program", "level_term")
    optional = ("title_bn", "type", "elective")
    sample = (
        ("CSE", "CSE101", "Programming Basics", "3", "BSC-CSE", "Level 1 Term 1", "", "theory", ""),
        ("CSE", "CSE102", "Programming Lab", "1.5", "BSC-CSE", "Level 1 Term 1", "", "lab", "no"),
    )

    def __init__(self, **options):
        super().__init__(**options)
        self._taken = set(self.lookups.courses)

    def clean(self, row):
        department = self.lookups.department(row)
        code = _text(row, "code", max_length=20, required=True)
        key = (department.pk, code.casefold())
        if key in self._taken:
            raise RowInvalid("code", _("This department already has a course with this code."))
        self._taken.add(key)
        title = _text(row, "title", max_length=200, required=True)
        title_bn = _text(row, "title_bn", max_length=200)
        return Course(
            department=department,
            code=code,
            title=title,
            title_bn=title_bn,
            credit=self._credit(row),
            course_type=self._type(row),
            program=self.lookups.program(row, department),
            level_term=self.lookups.level_term(row),
            is_elective=_flag(row, "elective"),
        )

    @staticmethod
    def _credit(row: dict) -> Decimal:
        value = row.get("credit", "")
        try:
            credit = Decimal(value)
        except InvalidOperation:
            raise RowInvalid("credit", _("Enter a number such as 3 or 1.5.")) from None
        if (
            not credit.is_finite()
            or credit <= 0
            or credit >= 100
            or credit.as_tuple().exponent < -1
        ):
            raise RowInvalid(
                "credit", _("The credit must be above zero, below 100, with one decimal at most.")
            )
        return credit

    @staticmethod
    def _type(row: dict) -> str:
        word = row.get("type", "").casefold()
        if not word:
            return CourseType.THEORY
        for value, label in CourseType.choices:
            if word in {value, str(label).casefold()}:
                return value
        raise RowInvalid("type", _("Use theory or lab."))

    def save(self, records, *, with_codes):
        Course.objects.bulk_create(records, batch_size=BULK_BATCH)
        return []


class OfferingImporter(Importer):
    key = "offerings"
    title = gettext_lazy("Course offerings")
    summary = gettext_lazy("Offers courses in a semester with the teacher who takes them.")
    required = ("department", "course_code", "semester", "teacher_id")
    optional = ("section",)
    sample = (
        ("CSE", "CSE101", "Spring 2026", "T0001", "A"),
        ("CSE", "CSE102", "Spring 2026", "T0002", ""),
    )

    def __init__(self, **options):
        super().__init__(**options)
        self._taken = set(CourseOffering.objects.values_list("course_id", "semester_id", "section"))
        self._teachers = dict(
            TeacherProfile.objects.values_list("registry__external_id_index", "pk")
        )

    def clean(self, row):
        department = self.lookups.department(row)
        course = self.lookups.course(row, department)
        semester = self.lookups.semester(row)
        teacher_id = _text(row, "teacher_id", max_length=32, required=True)
        try:
            teacher = self._teachers[registry_index(teacher_id)]
        except KeyError:
            raise RowInvalid("teacher_id", _("No registered teacher has this ID.")) from None
        section = _text(row, "section", max_length=16)
        key = (course.pk, semester.pk, section)
        if key in self._taken:
            raise RowInvalid(
                "section", _("This course is already offered in this semester with this section.")
            )
        self._taken.add(key)
        return CourseOffering(course=course, semester=semester, teacher_id=teacher, section=section)

    def save(self, records, *, with_codes):
        CourseOffering.objects.bulk_create(records, batch_size=BULK_BATCH)
        return []


class EnrollmentImporter(Importer):
    key = "enrollments"
    title = gettext_lazy("Enrollments")
    summary = gettext_lazy("Enrolls students in course offerings (regular or retake).")
    required = ("student_id", "department", "course_code", "semester")
    optional = ("section", "status")
    sample = (
        ("2101001", "CSE", "CSE101", "Spring 2026", "A", "regular"),
        ("2101002", "CSE", "CSE101", "Spring 2026", "A", "retake"),
    )

    def __init__(self, **options):
        super().__init__(**options)
        self._students = dict(
            StudentProfile.objects.values_list("registry__external_id_index", "pk")
        )
        self._offerings = {
            (department_id, code.casefold(), semester_id, section): pk
            for pk, department_id, code, semester_id, section in CourseOffering.objects.values_list(
                "pk", "course__department_id", "course__code", "semester_id", "section"
            )
        }
        self._seen: set[tuple[int, int]] = set()

    def clean(self, row):
        student_id = _text(row, "student_id", max_length=32, required=True)
        try:
            student = self._students[registry_index(student_id)]
        except KeyError:
            raise RowInvalid("student_id", _("No registered student has this ID.")) from None
        department = self.lookups.department(row)
        course = self.lookups.course(row, department)
        semester = self.lookups.semester(row)
        section = _text(row, "section", max_length=16)
        try:
            offering = self._offerings[
                (department.pk, course.code.casefold(), semester.pk, section)
            ]
        except KeyError:
            raise RowInvalid("course_code", _("This course is not offered like this.")) from None
        if (student, offering) in self._seen:
            raise RowInvalid("student_id", _("This student is listed for this offering twice."))
        self._seen.add((student, offering))
        return Enrollment(
            student_profile_id=student, offering_id=offering, status=self._status(row)
        )

    @staticmethod
    def _status(row: dict) -> str:
        word = row.get("status", "").casefold()
        if word in {"", EnrollmentStatus.REGULAR}:
            return EnrollmentStatus.REGULAR
        if word == EnrollmentStatus.RETAKE:
            return EnrollmentStatus.RETAKE
        raise RowInvalid("status", _("Use regular or retake."))

    def finish(self, records):
        offering_ids = {record.offering_id for _line, record in records}
        stored = set(
            Enrollment.objects.filter(offering_id__in=offering_ids).values_list(
                "student_profile_id", "offering_id"
            )
        )
        return [
            RowError(line, "student_id", _("This student is already enrolled in this offering."))
            for line, record in records
            if (record.student_profile_id, record.offering_id) in stored
        ]

    def save(self, records, *, with_codes):
        Enrollment.objects.bulk_create(records, batch_size=BULK_BATCH)
        return []


class ResultImporter(EnrollmentImporter):
    key = "results"
    title = gettext_lazy("Results")
    summary = gettext_lazy(
        "Adds grades to existing enrollments. Grades already entered are changed on the "
        "results screen."
    )
    required = ("student_id", "department", "course_code", "semester", "grade")
    optional = ("section", "published")
    sample = (
        ("2101001", "CSE", "CSE101", "Spring 2026", "A+", "A", "no"),
        ("2101002", "CSE", "CSE101", "Spring 2026", "B-", "A", "no"),
    )

    def __init__(self, **options):
        super().__init__(**options)
        self._enrollments = {
            (student, offering): pk
            for pk, student, offering in Enrollment.objects.values_list(
                "pk", "student_profile_id", "offering_id"
            )
        }
        self._grades = {grade.letter.casefold(): grade for grade in GradeScale.objects.all()}

    def clean(self, row):
        enrollment = super().clean(row)
        key = (enrollment.student_profile_id, enrollment.offering_id)
        if key not in self._enrollments:
            raise RowInvalid("student_id", _("This student is not enrolled in this offering."))
        letter = _text(row, "grade", max_length=4, required=True)
        try:
            grade = self._grades[letter.casefold()]
        except KeyError:
            raise RowInvalid(
                "grade", _("Unknown grade “%(value)s”.") % {"value": _shown(letter)}
            ) from None
        return Result(
            enrollment_id=self._enrollments[key],
            grade=grade,
            points=grade.points,
            published=_flag(row, "published"),
        )

    def finish(self, records):
        stored = set(
            Result.objects.filter(
                enrollment_id__in=[record.enrollment_id for _line, record in records]
            ).values_list("enrollment_id", flat=True)
        )
        return [
            RowError(line, "student_id", _("This student already has a result in this offering."))
            for line, record in records
            if record.enrollment_id in stored
        ]

    def save(self, records, *, with_codes):
        Result.objects.bulk_create(records, batch_size=BULK_BATCH)
        return []


IMPORTERS: dict[str, type[Importer]] = {
    importer.key: importer
    for importer in (
        StudentImporter,
        TeacherImporter,
        CourseImporter,
        OfferingImporter,
        EnrollmentImporter,
        ResultImporter,
    )
}


def template_rows(importer: type[Importer]) -> list[tuple[str, ...]]:
    """Header and example rows of the downloadable CSV template (columns in ``columns`` order)."""
    return [importer.required + importer.optional, *importer.sample]


def decode(data: bytes) -> str:
    """The upload as text: size-limited, UTF-8 with or without the BOM Excel adds."""
    if len(data) > MAX_BYTES:
        raise ImportRejected(
            _("The file is too large. The limit is %(mb)d MB."), params={"mb": MAX_BYTES >> 20}
        )
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise ImportRejected(
            _("The file must be saved as UTF-8 (in Excel: “CSV UTF-8”).")
        ) from None
    if "\x00" in text:
        raise ImportRejected(_("The file is not a text CSV file."))
    return text


def _check_header(importer: Importer, header: list[str]) -> list[str]:
    names = [cell.strip().casefold() for cell in header]
    duplicated = sorted({name for name in names if names.count(name) > 1})
    missing = [name for name in importer.required if name not in names]
    unknown = [name for name in names if name not in importer.columns]
    if duplicated or missing or unknown:
        problems = []
        if missing:
            problems.append(_("missing: %(names)s") % {"names": ", ".join(missing)})
        if unknown:
            problems.append(
                _("not allowed: %(names)s") % {"names": ", ".join(map(_shown, unknown))}
            )
        if duplicated:
            problems.append(
                _("repeated: %(names)s") % {"names": ", ".join(map(_shown, duplicated))}
            )
        raise ImportRejected(
            _("The header row does not match the template (%(problems)s).")
            % {"problems": "; ".join(problems)}
        )
    return names


def _read(importer: Importer, text: str) -> tuple[list[tuple[int, dict]], list[RowError], int]:
    reader = csv.reader(io.StringIO(text, newline=""))
    try:
        header = next(reader, None)
        if header is None:
            raise ImportRejected(_("The file is empty."))
        names = _check_header(importer, header)
        rows, errors, sanitized = [], [], 0
        for cells in reader:
            if not any(cell.strip() for cell in cells):
                continue
            if len(rows) + len(errors) >= MAX_ROWS:
                raise ImportRejected(
                    _("The file has more than %(max)d rows."), params={"max": MAX_ROWS}
                )
            line = reader.line_num
            if len(cells) > len(names):
                errors.append(RowError(line, "", _("The row has more cells than the header.")))
                continue
            cleaned = [clean_cell(cell) for cell in cells]
            sanitized += sum(c != cell.strip() for c, cell in zip(cleaned, cells, strict=True))
            cleaned += [""] * (len(names) - len(cleaned))
            rows.append((line, dict(zip(names, cleaned, strict=True))))
    except csv.Error:
        raise ImportRejected(_("The file is not a valid CSV file.")) from None
    return rows, errors, sanitized


def _audit(action: str, importer: Importer, result: ImportResult, *, actor, request) -> None:
    audit.record(
        action,
        request=request,
        actor=actor,
        metadata={
            "kind": importer.key,
            "rows": result.total,
            "created": result.created,
            "errors": result.error_count,
            "sanitized_cells": result.sanitized,
            "codes_issued": len(result.issued),
        },
    )


def run(importer: Importer, text: str, *, apply: bool, actor, request=None) -> ImportResult:
    """Validate ``text`` and write it in one transaction; ``apply=False`` rolls that back."""
    rows, errors, sanitized = _read(importer, text)
    result = ImportResult(kind=importer.key, total=len(rows) + len(errors), sanitized=sanitized)
    records: list[tuple[int, object]] = []
    for line, row in rows:
        try:
            records.append((line, importer.clean(row)))
        except RowInvalid as error:
            errors.append(RowError(line, error.column, error.message))
    errors += importer.finish(records)
    errors.sort(key=lambda error: error.line)
    result.error_count = len(errors)
    result.errors = errors[:MAX_REPORTED_ERRORS]
    if errors:
        _audit(
            "import.rejected" if apply else "import.previewed",
            importer,
            result,
            actor=actor,
            request=request,
        )
        return result
    try:
        with transaction.atomic():
            result.issued = importer.save([record for _line, record in records], with_codes=apply)
            if not apply:
                transaction.set_rollback(True)
    except IntegrityError:
        raise ImportRejected(
            _("The data changed while the file was being imported. Nothing was saved; try again.")
        ) from None
    result.created = len(records)
    result.applied = apply
    _audit(
        "import.applied" if apply else "import.previewed",
        importer,
        result,
        actor=actor,
        request=request,
    )
    return result

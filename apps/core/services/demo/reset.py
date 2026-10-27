"""Remove the demo data: people by ``demo_`` username and ``DEMO-`` ID, and what hangs on them.

Structure rows (departments, courses, semesters, ...) are deleted by their demo names only
when nothing else uses them, so data of your own that shares a name is left alone. Audit events
are append-only and stay.
"""

from django.db import transaction
from django.db.models import ProtectedError, Q

from apps.academics.models import (
    Batch,
    Course,
    CourseOffering,
    Department,
    LevelTerm,
    Program,
    PromotionDecision,
    PromotionOverride,
    Result,
    Semester,
)
from apps.accounts.models import IdRegistry, StudentProfile, TeacherProfile, User, registry_index
from apps.core.services.demo import constants as c
from apps.core.services.demo.feedback import BANK_FILE
from apps.enrollment.models import Enrollment
from apps.feedback.models import (
    FeedbackResponse,
    FeedbackWindow,
    Question,
    QuestionCategory,
    SubmissionReceipt,
)
from apps.feedback.services import question_bank
from apps.notifications.models import DeliveryLog


def _delete_unused(queryset) -> None:
    """Delete each row that nothing else refers to; rows still in use stay."""
    for row in queryset:
        try:
            with transaction.atomic():
                row.delete()
        except ProtectedError:
            continue


@transaction.atomic
def delete_all() -> int:
    """Delete every demo object; returns how many accounts went."""
    registries = IdRegistry.objects.filter(
        external_id_index__in=[registry_index(external_id) for external_id in c.all_registry_ids()]
    )
    students = StudentProfile.objects.filter(registry__in=registries)
    teachers = TeacherProfile.objects.filter(registry__in=registries)
    offerings = CourseOffering.objects.filter(teacher__in=teachers)
    enrollments = Enrollment.objects.filter(
        Q(student_profile__in=students) | Q(offering__in=offerings)
    )
    FeedbackResponse.objects.filter(offering__in=offerings).delete()  # its answers go with it
    SubmissionReceipt.objects.filter(
        Q(student_profile__in=students) | Q(offering__in=offerings)
    ).delete()
    Result.objects.filter(enrollment__in=enrollments).delete()
    PromotionDecision.objects.filter(student_profile__in=students).delete()
    PromotionOverride.objects.filter(student_profile__in=students).delete()
    enrollments.delete()
    offerings.delete()
    FeedbackWindow.objects.filter(name__in=c.ROUNDS, semester__name__in=c.SEMESTERS).delete()
    account_ids = list(
        User.objects.filter(Q(username__in=c.USERNAMES) | Q(registry__in=registries)).values_list(
            "pk", flat=True
        )
    )
    students.delete()
    teachers.delete()
    registries.delete()
    DeliveryLog.objects.filter(user__in=account_ids).delete()
    User.objects.filter(pk__in=account_ids).delete()
    _delete_unused(Course.objects.filter(code__in=c.COURSE_CODES))
    _delete_unused(Batch.objects.filter(name=c.BATCH_NAME, program__code=c.PROGRAM_CODE))
    _delete_unused(Program.objects.filter(code=c.PROGRAM_CODE))
    _delete_unused(Semester.objects.filter(name__in=c.SEMESTERS))
    _delete_unused(LevelTerm.objects.filter(name__in=[name for name, _bn, _order in c.LEVEL_TERMS]))
    _delete_unused(Department.objects.filter(code__in=[code for code, _en, _bn in c.DEPARTMENTS]))
    bank = question_bank.parse(BANK_FILE.read_text(encoding="utf-8"))
    _delete_unused(Question.objects.filter(text__in=[row.text for row in bank.questions]))
    _delete_unused(QuestionCategory.objects.filter(name__in=[name for name, _bn in bank.topics]))
    return len(account_ids)

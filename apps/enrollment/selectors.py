"""Read-side queries over enrollment."""

from django.db.models import Exists, OuterRef

from apps.academics.services import semesters
from apps.accounts.models import AcademicStatus, StudentProfile
from apps.enrollment.models import Enrollment


def students_missing_enrollment():
    """Active students with no enrollment in any offering of the current semester."""
    enrolled = Enrollment.objects.filter(
        student_profile=OuterRef("pk"), offering__semester__in=semesters.ongoing()
    )
    return StudentProfile.objects.filter(academic_status=AcademicStatus.ACTIVE).exclude(
        Exists(enrolled)
    )

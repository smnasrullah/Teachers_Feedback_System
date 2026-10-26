"""Read-side queries over the academic structure."""

from apps.academics.models import Course, CourseOffering, LevelTerm, Outcome
from apps.accounts.models import StudentProfile
from apps.accounts.services.student_id_policy import with_visible_ids

# Badge variant and icon per outcome: the label always says it too, never colour alone.
OUTCOME_BADGES = {
    Outcome.PROMOTE: ("done", "check"),
    Outcome.PROMOTE_WITH_RETAKES: ("pending", "chevron-right"),
    Outcome.RETAIN: ("alert", "alert"),
    Outcome.GRADUATE: ("done", "award"),
}


def get_current_courses(student_profile) -> list[CourseOffering]:
    """Offerings of the current semester that ``student_profile`` is enrolled in."""
    return list(
        CourseOffering.objects.filter(
            semester__is_current=True, enrollments__student_profile=student_profile
        ).select_related("course", "semester", "teacher__registry")
    )


def _badge(outcome: str) -> dict:
    variant, icon = OUTCOME_BADGES[outcome]
    return {"label": Outcome(outcome).label, "variant": variant, "icon": icon}


def promotion_rows(decisions, viewer) -> list[dict]:
    """Display rows for promotion decisions: level/term names, course codes, outcome badges,
    and the student's ID and name only where ``viewer`` may see them."""
    students = {
        student.pk: student
        for student in with_visible_ids(
            StudentProfile.objects.filter(
                pk__in=[decision.student_profile_id for decision in decisions]
            ).select_related("program"),
            viewer,
        )
    }
    level_terms = {level_term.pk: level_term for level_term in LevelTerm.objects.all()}
    course_ids = {
        course
        for decision in decisions
        for course in (*decision.failed_course_ids, *decision.unplaced_course_ids)
    }
    codes = dict(Course.objects.filter(pk__in=course_ids).values_list("pk", "code"))
    return [
        {
            "decision": decision,
            "student": students[decision.student_profile_id],
            "from": level_terms[decision.from_level_term_id],
            "to": level_terms[decision.to_level_term_id],
            "failed": [codes[course] for course in decision.failed_course_ids],
            "unplaced": [codes[course] for course in decision.unplaced_course_ids],
            "computed": _badge(decision.computed),
            "outcome": _badge(decision.outcome),
        }
        for decision in decisions
    ]

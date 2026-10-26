"""Role and head-of-department (HOD) assignment. Both change who sees what, so both are audited."""

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils.translation import gettext as _

from apps.accounts.models import IdType, RegistryStatus, TeacherProfile, User
from apps.auditlog.services import audit
from apps.core.permissions import Role

# Students stay students: their profile, enrolment and results hang off a student ID.
CHANGEABLE_ROLES = (Role.TEACHER, Role.ADMIN)


def _drop_hod(profile: TeacherProfile) -> None:
    profile.is_hod = False
    profile.hod_department = None
    profile.save(update_fields=["is_hod", "hod_department"])


@transaction.atomic
def change_role(user: User, new_role: str, *, actor, request=None) -> bool:
    """Switch a teacher account to Admin or back. Returns whether anything changed."""
    user = User.objects.select_for_update().get(pk=user.pk)
    if new_role not in CHANGEABLE_ROLES or user.role not in CHANGEABLE_ROLES:
        raise ValidationError(_("This account's role cannot be changed."), code="role_fixed")
    if user.pk == actor.pk:
        raise ValidationError(_("You cannot change your own role."), code="role_self")
    if new_role == user.role:
        return False
    profile = user.teacher_profile
    if new_role == Role.TEACHER and profile is None:
        raise ValidationError(
            _("Only an account created from a teacher ID can become a teacher."),
            code="role_needs_teacher_id",
        )
    previous = user.role
    user.role = new_role
    user.save(update_fields=["role"])
    if new_role == Role.ADMIN and profile is not None and profile.is_hod:
        _drop_hod(profile)
    audit.record(
        "user.role_changed",
        request=request,
        actor=actor,
        target=user,
        department_id=user.department_id,
        metadata={"from": previous, "to": new_role},
    )
    return True


@transaction.atomic
def assign_hod(
    profile: TeacherProfile, department, *, actor, request=None
) -> TeacherProfile | None:
    """Make ``profile`` head of ``department``; returns the previous head it replaced, if any."""
    profile = (
        TeacherProfile.objects.select_for_update().select_related("registry").get(pk=profile.pk)
    )
    registry = profile.registry
    if registry.status == RegistryStatus.REVOKED or registry.id_type != IdType.TEACHER:
        raise ValidationError(
            _("This teacher cannot be made head of department."), code="hod_ineligible"
        )
    account = registry.claimed_by
    if account is not None and account.role != Role.TEACHER:
        raise ValidationError(_("Only teachers can be head of department."), code="hod_not_teacher")
    replaced = (
        TeacherProfile.objects.select_for_update()
        .filter(is_hod=True, hod_department=department)
        .exclude(pk=profile.pk)
        .first()
    )
    if replaced is not None:
        _drop_hod(replaced)
        audit.record(
            "hod.removed",
            request=request,
            actor=actor,
            target=replaced,
            department_id=department.pk,
            metadata={"replaced_by": profile.pk},
        )
    profile.is_hod = True
    profile.hod_department = department
    profile.save(update_fields=["is_hod", "hod_department"])
    audit.record(
        "hod.assigned",
        request=request,
        actor=actor,
        target=profile,
        department_id=department.pk,
        metadata={"replaced": replaced.pk if replaced is not None else None},
    )
    return replaced


@transaction.atomic
def remove_hod(profile: TeacherProfile, *, actor, request=None) -> bool:
    profile = TeacherProfile.objects.select_for_update().get(pk=profile.pk)
    if not profile.is_hod:
        return False
    department_id = profile.hod_department_id
    _drop_hod(profile)
    audit.record(
        "hod.removed",
        request=request,
        actor=actor,
        target=profile,
        department_id=department_id,
        metadata={},
    )
    return True

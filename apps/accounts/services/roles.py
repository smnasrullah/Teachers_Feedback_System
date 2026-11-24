"""Role and head-of-department (HOD) assignment. Both change who sees what, so both are audited,
and a change of head signs the people concerned out so their next login has the new rights.

HOD is not a stored role: it is a teacher whose profile carries the flag and the department
(at most one head per department, a database constraint). The Admin names a head on the
teacher's registry entry or in the teacher import; both end in ``set_teacher_role``.
"""

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import TextChoices
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy

from apps.accounts.models import IdType, RegistryStatus, TeacherProfile, User
from apps.auditlog.services import audit
from apps.core.models import ActiveSession
from apps.core.permissions import Role

# Students stay students: their profile, enrolment and results hang off a student ID.
CHANGEABLE_ROLES = (Role.TEACHER, Role.ADMIN)


class TeacherRole(TextChoices):
    """What the Admin registers a teacher ID as."""

    TEACHER = "teacher", gettext_lazy("Teacher")
    HOD = "hod", gettext_lazy("Head of department (HOD)")


def _end_sessions(*profiles: TeacherProfile) -> None:
    """Sign the accounts out everywhere, so the next login carries the changed rights."""
    accounts = [p.registry.claimed_by_id for p in profiles if p.registry.claimed_by_id]
    ActiveSession.objects.filter(user_id__in=accounts).delete()


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


def current_head(department, *, exclude=None) -> TeacherProfile | None:
    """The teacher heading ``department`` now (other than ``exclude``), if any."""
    if department is None:
        return None
    heads = TeacherProfile.objects.select_related("registry").filter(
        is_hod=True, hod_department=department
    )
    return heads.exclude(pk=getattr(exclude, "pk", None)).first()


def head_exists_error(department) -> ValidationError:
    return ValidationError(
        _(
            "%(department)s already has a head of department. Confirm that this teacher "
            "replaces them; the current head stays on as a teacher."
        ),
        code="hod_exists",
        params={"department": department.code},
    )


@transaction.atomic
def assign_hod(
    profile: TeacherProfile, department, *, replace: bool = False, actor, request=None
) -> TeacherProfile | None:
    """Make ``profile`` head of ``department``; returns the previous head it replaced, if any.

    A department that already has a head needs ``replace=True`` (the Admin's explicit
    confirmation); the previous head then becomes a normal teacher, in the same transaction.
    """
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
        .select_related("registry")
        .filter(is_hod=True, hod_department=department)
        .exclude(pk=profile.pk)
        .first()
    )
    if replaced is not None and not replace:
        raise head_exists_error(department)
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
    _end_sessions(profile, *([replaced] if replaced is not None else []))
    return replaced


@transaction.atomic
def remove_hod(profile: TeacherProfile, *, actor, request=None) -> bool:
    """Make a head of department a normal teacher again (the account is kept)."""
    profile = (
        TeacherProfile.objects.select_for_update().select_related("registry").get(pk=profile.pk)
    )
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
    _end_sessions(profile)
    return True


@transaction.atomic
def set_teacher_role(
    profile: TeacherProfile, role: str, *, replace: bool = False, actor, request=None
) -> TeacherProfile | None:
    """Register or edit a teacher as a teacher or as head of their own department.

    Promoting names them head of their registry entry's department (``replace`` confirms
    taking over from a current head); demoting keeps them as a teacher. Returns the head
    who was replaced, if any. Nothing changes (and nobody is signed out) when the role is
    already what was asked.
    """
    profile = TeacherProfile.objects.select_related("registry").get(pk=profile.pk)
    if role == TeacherRole.HOD:
        department = profile.registry.department
        if profile.is_hod and profile.hod_department_id == department.pk:
            return None
        return assign_hod(profile, department, replace=replace, actor=actor, request=request)
    remove_hod(profile, actor=actor, request=request)
    return None

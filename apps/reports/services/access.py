"""Who may open the report of an offering (BLUEPRINT §5.3).

Its teacher reads it and writes the "action taken" note; the head of the offering's department
and an Admin read it, the note included. Everyone else is refused.
"""

from dataclasses import dataclass

from django.core.exceptions import PermissionDenied

from apps.core.permissions import Role, has_role


@dataclass(frozen=True)
class Access:
    can_write_note: bool


def access_for(user, offering) -> Access:
    """What ``user`` may do with the report of ``offering``; ``PermissionDenied`` if nothing."""
    if has_role(user, Role.ADMIN):
        return Access(can_write_note=False)
    profile = user.teacher_profile
    if profile is not None:
        if offering.teacher_id == profile.pk:
            return Access(can_write_note=True)
        if profile.is_hod and profile.hod_department_id == offering.course.department_id:
            return Access(can_write_note=False)
    raise PermissionDenied

"""``{{ profile|student_id:request.user }}``: the ID, or a mask when the viewer may not see it."""

from django import template

from apps.accounts.services import student_id_policy as policy

register = template.Library()


def _may_see(profile, viewer) -> bool:
    # A queryset prepared by ``with_visible_ids`` already decided per row.
    if hasattr(profile, "ids_visible"):
        return profile.ids_visible
    return policy.can_view_student_id(viewer, profile)


@register.filter
def student_id(profile, viewer):
    if not _may_see(profile, viewer):
        return policy.MASK
    if hasattr(profile, "visible_student_id"):
        return profile.visible_student_id
    return profile.registry.external_id


@register.filter
def student_name(profile, viewer):
    """The full name (empty when none is on file), or a mask when the viewer may not see it."""
    if not _may_see(profile, viewer):
        return policy.MASK
    name = (
        profile.visible_full_name
        if hasattr(profile, "visible_full_name")
        else profile.registry.full_name
    )
    return name or ""

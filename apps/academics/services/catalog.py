"""Create, change and delete academic records; every change is audited."""

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import ProtectedError
from django.utils.translation import gettext as _

from apps.academics.models import Semester
from apps.auditlog.services import audit


def _describe_blockers(blockers) -> str:
    counts: dict[str, int] = {}
    for blocker in blockers:
        name = str(blocker._meta.verbose_name_plural)
        counts[name] = counts.get(name, 0) + 1
    return ", ".join(f"{count} {name}" for name, count in sorted(counts.items()))


def _audit_department_id(screen, obj) -> int | None:
    return screen.department_of(obj) if screen.department_of else None


@transaction.atomic
def save(screen, form, *, actor, request=None):
    """Save a validated ModelForm and audit it; choosing a current semester demotes the old one."""
    created = form.instance.pk is None
    changed = [] if created else sorted(set(form.changed_data) & set(form._meta.fields))
    if not created and not changed:
        return form.instance
    obj = form.save(commit=False)
    if isinstance(obj, Semester) and obj.is_current:
        Semester.objects.filter(is_current=True).exclude(pk=obj.pk).update(is_current=False)
    obj.save()
    form.save_m2m()
    audit.record(
        f"academics.{'created' if created else 'updated'}",
        request=request,
        actor=actor,
        target=obj,
        department_id=_audit_department_id(screen, obj),
        metadata={"entity": screen.key, "changed": changed},
    )
    return obj


@transaction.atomic
def delete(screen, obj, *, actor, request=None) -> None:
    """Delete ``obj`` unless other records depend on it (then raise a friendly error)."""
    department_id = _audit_department_id(screen, obj)
    audit.record(
        "academics.deleted",
        request=request,
        actor=actor,
        target=obj,
        department_id=department_id,
        metadata={"entity": screen.key},
    )
    try:
        obj.delete()
    except ProtectedError as error:
        raise ValidationError(
            _("This %(what)s cannot be deleted because it is still used by: %(blockers)s.")
            % {
                "what": screen.model._meta.verbose_name,
                "blockers": _describe_blockers(error.protected_objects),
            }
        ) from None

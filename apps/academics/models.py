"""Minimal academic structure needed by identity (P04). P06 adds CRUD and the rest."""

from django.db import models
from django.utils.translation import gettext_lazy as _


class Department(models.Model):
    code = models.CharField(_("code"), max_length=16, unique=True)
    name = models.CharField(_("name"), max_length=150)
    name_bn = models.CharField(_("name (Bangla)"), max_length=150, blank=True)
    is_active = models.BooleanField(_("active"), default=True)

    class Meta:
        ordering = ["code"]
        verbose_name = _("department")
        verbose_name_plural = _("departments")

    def __str__(self):
        return self.code


class Program(models.Model):
    department = models.ForeignKey(
        Department, on_delete=models.PROTECT, related_name="programs", verbose_name=_("department")
    )
    code = models.CharField(_("code"), max_length=16)
    name = models.CharField(_("name"), max_length=150)
    name_bn = models.CharField(_("name (Bangla)"), max_length=150, blank=True)

    class Meta:
        ordering = ["department__code", "code"]
        verbose_name = _("program")
        verbose_name_plural = _("programs")
        constraints = [
            models.UniqueConstraint(fields=["department", "code"], name="program_unique_code")
        ]

    def __str__(self):
        return f"{self.department.code} {self.code}"


class Batch(models.Model):
    program = models.ForeignKey(
        Program, on_delete=models.PROTECT, related_name="batches", verbose_name=_("program")
    )
    name = models.CharField(_("name"), max_length=50)

    class Meta:
        ordering = ["program__code", "-name"]
        verbose_name = _("batch")
        verbose_name_plural = _("batches")
        constraints = [
            models.UniqueConstraint(fields=["program", "name"], name="batch_unique_name")
        ]

    def __str__(self):
        return f"{self.program.code} {self.name}"


class LevelTerm(models.Model):
    """One step of the curriculum (for example "Level 2, Term 1").

    How many exist is data, not code: the admin defines as many ordered rows as the
    university's scheme needs. ``order`` is unique and drives promotion order.
    """

    name = models.CharField(_("name"), max_length=50)
    name_bn = models.CharField(_("name (Bangla)"), max_length=50, blank=True)
    order = models.PositiveSmallIntegerField(_("order"), unique=True)

    class Meta:
        ordering = ["order"]
        verbose_name = _("level/term")
        verbose_name_plural = _("levels/terms")

    def __str__(self):
        return self.name

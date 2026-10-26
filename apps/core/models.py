from django.conf import settings
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _


class ActiveSession(models.Model):
    """The one login a user may currently use (single active session per user).

    ``login_id`` is a random value also stored inside that login's session; any other
    session of the same user carries a different value and is signed out on its next
    request. Deleting the row signs out every device.
    """

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="+", verbose_name=_("user")
    )
    login_id = models.CharField(_("login id"), max_length=64)
    created_at = models.DateTimeField(_("signed in at"), default=timezone.now)
    ip = models.GenericIPAddressField(_("IP address"), null=True, blank=True)
    user_agent = models.CharField(_("browser"), max_length=255, blank=True)

    class Meta:
        verbose_name = _("active session")
        verbose_name_plural = _("active sessions")

    def __str__(self):
        return f"ActiveSession({self.user_id})"


class SystemSetting(models.Model):
    """One value the Admin changed from its default in ``settings``.

    Only overrides are stored; ``apps.core.services.system_settings`` knows the keys, their
    limits and their defaults, and is the only code that reads or writes this table.
    """

    key = models.CharField(_("setting"), max_length=64, unique=True)
    value = models.JSONField(_("value"))
    updated_at = models.DateTimeField(_("updated at"), auto_now=True)

    class Meta:
        ordering = ["key"]
        verbose_name = _("system setting")
        verbose_name_plural = _("system settings")

    def __str__(self):
        return self.key

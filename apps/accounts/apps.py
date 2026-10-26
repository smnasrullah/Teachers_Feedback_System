from django.apps import AppConfig


class AccountsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.accounts"

    def ready(self):
        from axes.signals import user_locked_out

        from apps.accounts.services.login import record_lockout

        user_locked_out.connect(record_lockout, dispatch_uid="accounts.audit_lockout")

from django.contrib.auth.signals import user_logged_in, user_logged_out
from django.dispatch import receiver

from .services import sessions


@receiver(user_logged_in, dispatch_uid="core.start_session")
def start_session(sender, request, user, **kwargs):
    sessions.start(request, user)


@receiver(user_logged_out, dispatch_uid="core.end_session")
def end_session(sender, request, user, **kwargs):
    sessions.end(request, user)

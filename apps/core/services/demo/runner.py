"""Demo accounts and demo data for development (``manage.py seed_demo``).

``seed`` is idempotent: every step looks for what it would create and skips it, so a second
run changes nothing. It refuses to run anywhere but the development settings, so no demo
password or authenticator key can ever exist in another environment.
"""

from dataclasses import dataclass

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils.translation import gettext as _

from apps.accounts.models import User
from apps.accounts.services import twofactor
from apps.accounts.services.passwords import validate_strong_password
from apps.core.services.demo import academics, constants, feedback, notices, people, reset

DEV_SETTINGS = "config.settings.dev"
USERNAMES = constants.USERNAMES


@dataclass(frozen=True)
class Account:
    username: str
    totp_key: str


@dataclass(frozen=True)
class Report:
    accounts: tuple[Account, ...]
    password: str | None  # shown once; None when the accounts already existed and are unchanged
    password_generated: bool
    spare_codes: tuple[tuple[str, str], ...]
    submitted: int  # forms submitted by this run


def require_development() -> None:
    if not settings.DEBUG or settings.SETTINGS_MODULE != DEV_SETTINGS:
        raise ValidationError(
            _("The demo data only exists with DEBUG on and DJANGO_SETTINGS_MODULE=%(module)s.")
            % {"module": DEV_SETTINGS}
        )


def delete_all() -> int:
    """Remove the demo data; returns how many accounts were deleted."""
    require_development()
    return reset.delete_all()


def _teacher_means(cast) -> dict[int, float]:
    return {cast.teachers[spec.key].pk: spec.mean for spec in constants.TEACHERS}


@transaction.atomic
def seed(password: str | None = None) -> Report:
    """Create the demo data that is missing. ``password`` (checked against the strict rule) is
    set on the three accounts; without one, a random password is made when any is missing."""
    require_development()
    generated = password is None and User.objects.filter(username__in=USERNAMES).count() < len(
        USERNAMES
    )
    if password is not None:
        validate_strong_password(password)
    elif generated:
        password = people.generate_password()
    structure = academics.ensure_structure()
    admin = people.ensure_admin(password)
    cast = people.build(structure, admin, password)
    for user in (cast.admin, cast.hod, cast.student):
        people.sync_password(user, password)
    offerings = academics.ensure_offerings(structure, cast.teachers)
    academics.enroll_spring(offerings, cast.cse, cast.eee)
    academics.publish_results(offerings, cast.cse, cast.eee, admin)
    academics.promote_cse(structure.semesters[constants.SPRING], cast.cse, admin)
    feedback.ensure_bank(admin)
    closed, open_ = feedback.ensure_rounds(structure)
    means = _teacher_means(cast)
    closed_new = feedback.submit_all(
        closed, feedback.closed_round_items(closed, offerings, cast.cse, cast.eee), means
    )
    open_new = feedback.submit_all(
        open_, feedback.open_round_items(open_, offerings, cast.cse), means
    )
    if closed_new:
        feedback.moderate(closed, admin)
    feedback.add_notes(closed, offerings)
    notices.send_all(
        cast,
        closed,
        open_,
        str(offerings[constants.FALL, constants.FALL_COURSES[0]].course),
        len(constants.FALL_COURSES) - len(constants.DEMO_STUDENT_SEALED),
    )
    accounts = tuple(
        Account(user.username, twofactor.manual_key(user.totp_secret))
        for user in User.objects.filter(username__in=USERNAMES).order_by("username")
    )
    return Report(accounts, password, generated, cast.spare_codes, closed_new + open_new)

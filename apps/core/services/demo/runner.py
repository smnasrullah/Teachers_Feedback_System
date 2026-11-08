"""Demo accounts and data for development, isolated demo, or explicitly enabled public demo.

``seed`` is idempotent: every step looks for what it would create and skips it, so a second
run changes nothing. Production seeding requires an explicit public-demo setting and PostgreSQL.
"""

from dataclasses import dataclass

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import connection, transaction
from django.utils.translation import gettext as _

from apps.accounts.models import User
from apps.accounts.services import twofactor
from apps.accounts.services.passwords import validate_strong_password
from apps.core.services.demo import academics, constants, feedback, notices, people, reset

DEV_SETTINGS = "config.settings.dev"
DEMO_SETTINGS = "config.settings.demo"
PROD_SETTINGS = "config.settings.prod"
USERNAMES = constants.USERNAMES
SEED_LOCK_ID = 0x54465344  # "TFSD"; serializes startup seeds across web instances.


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


def require_seed_environment() -> None:
    local_dev = settings.DEBUG and settings.SETTINGS_MODULE == DEV_SETTINGS
    isolated_demo = (
        not settings.DEBUG
        and settings.SETTINGS_MODULE == DEMO_SETTINGS
        and settings.IS_DEMO_SITE
        and settings.DEMO_DATABASE_ISOLATED
        and settings.DATABASES["default"]["ENGINE"] == "django.db.backends.postgresql"
    )
    public_demo = (
        not settings.DEBUG
        and settings.SETTINGS_MODULE == PROD_SETTINGS
        and settings.IS_DEMO_SITE
        and settings.PUBLIC_DEMO_ENABLED
        and settings.DATABASES["default"]["ENGINE"] == "django.db.backends.postgresql"
    )
    if not (local_dev or isolated_demo or public_demo):
        raise ValidationError(
            _(
                "Demo data can be seeded only with local development settings, an isolated demo "
                "deployment, or production with PUBLIC_DEMO_ENABLED on PostgreSQL."
            )
        )


def _lock_seed() -> None:
    """Ensure only one Render instance mutates the demo dataset at a time."""
    if connection.vendor == "postgresql":
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_xact_lock(%s)", [SEED_LOCK_ID])


@transaction.atomic
def delete_all() -> int:
    """Remove the demo data; returns how many accounts were deleted."""
    require_seed_environment()
    _lock_seed()
    return reset.delete_all()


def _teacher_means(cast) -> dict[int, float]:
    return {cast.teachers[spec.key].pk: spec.mean for spec in constants.TEACHERS}


@transaction.atomic
def seed(password: str | None = None) -> Report:
    """Create the demo data that is missing. ``password`` (checked against the strict rule) is
    set on the four accounts; without one, a random password is made when any is missing."""
    require_seed_environment()
    _lock_seed()
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
    for user in (cast.admin, cast.hod, cast.teacher, cast.student):
        people.sync_password(user, password)
    offerings = academics.ensure_offerings(structure, cast.teachers)
    academics.enroll_winter(offerings, cast.cse, cast.eee)
    academics.publish_results(offerings, cast.cse, cast.eee, admin)
    academics.promote_cse(structure.semesters[constants.WINTER], cast.cse, admin)
    feedback.ensure_bank(admin)
    closed, early, open_ = feedback.ensure_rounds(structure)
    means = _teacher_means(cast)
    closed_new = feedback.submit_all(
        closed, feedback.closed_round_items(closed, offerings, cast.cse, cast.eee), means
    )
    early_new = feedback.submit_all(
        early, feedback.early_round_items(early, offerings, cast.cse), means
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
        str(offerings[constants.SUMMER, constants.SUMMER_COURSES[0]].course),
        len(constants.SUMMER_COURSES) - len(constants.DEMO_STUDENT_SEALED),
    )
    accounts = tuple(
        Account(user.username, twofactor.manual_key(user.totp_secret))
        for user in User.objects.filter(username__in=USERNAMES).order_by("username")
    )
    return Report(
        accounts, password, generated, cast.spare_codes, closed_new + early_new + open_new
    )

"""Demo people: the four login accounts, the teachers and the synthetic students.

Everything goes through the services the real screens use (registry, activation codes,
sign-up), so the accounts are indistinguishable from ones created by hand. Passwords and
authenticator keys are returned to the caller to print; they are never stored in a file or
the audit trail.
"""

import secrets
from dataclasses import dataclass

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils.translation import gettext as _

from apps.accounts.models import (
    IdRegistry,
    IdType,
    StudentProfile,
    TeacherProfile,
    User,
    registry_index,
)
from apps.accounts.services import registry as registry_service
from apps.accounts.services import signup, twofactor
from apps.accounts.services.passwords import validate_strong_password
from apps.auditlog.services import audit
from apps.core.services.demo import constants as c
from apps.core.services.demo.academics import Structure

PASSWORD_LENGTH = 16
PASSWORD_GROUPS = (
    "ABCDEFGHJKLMNPQRSTUVWXYZ",
    "abcdefghijkmnopqrstuvwxyz",
    "23456789",
    "-_!@#",
)
MAX_PASSWORD_TRIES = 20
CSE_LEVELS = (c.L1T2,) * len(c.CSE_STUDENT_IDS)  # promoted to Level 2 Term I by the seeder
EEE_LEVELS = (c.L2T1,) * c.EEE_FINAL_YEAR + (c.L2T2,)


@dataclass(frozen=True)
class Cast:
    admin: User
    hod: User
    teacher: User
    student: User
    teachers: dict[str, TeacherProfile]
    cse: list[StudentProfile]  # in ID order; the first is demo_student
    eee: list[StudentProfile]
    spare_codes: tuple[tuple[str, str], ...]  # (student ID, activation code), shown once


def generate_password() -> str:
    """A random password that passes the strict rule (the demo accounts use it)."""
    alphabet = "".join(PASSWORD_GROUPS)
    for _attempt in range(MAX_PASSWORD_TRIES):
        chars = [secrets.choice(group) for group in PASSWORD_GROUPS]
        chars += [secrets.choice(alphabet) for _n in range(PASSWORD_LENGTH - len(chars))]
        secrets.SystemRandom().shuffle(chars)
        password = "".join(chars)
        try:
            validate_strong_password(password)
        except ValidationError:
            continue
        return password
    raise RuntimeError("Could not generate a password.")


def sync_password(user: User, password: str | None) -> None:
    """Make ``password`` the account's password (nothing changes when it already is)."""
    if password and not user.check_password(password):
        user.set_password(password)
        user.save(update_fields=["password"])


def ensure_admin(password: str | None) -> User:
    user = User.objects.filter(username=c.ADMIN).first()
    if user is None:
        with transaction.atomic():
            user = User.objects.create_admin(
                password, username=c.ADMIN, nickname=c.NICKNAMES[c.ADMIN]
            )
            twofactor.activate(user, twofactor.new_secret(), 0)
            audit.record("admin.created", target=user, metadata={"via": "seed_demo"})
    return user


def _register(id_type, external_id, full_name, department, profile, actor):
    """The registry row of ``external_id`` and whether this call created it."""
    registry = IdRegistry.objects.filter(
        id_type=id_type, external_id_index=registry_index(external_id)
    ).first()
    if registry is not None:
        return registry, False
    created = registry_service.register(
        id_type,
        external_id=external_id,
        full_name=full_name,
        department=department,
        profile=profile,
        actor=actor,
    )
    return created, True


def _login_for(registry, username, password, actor) -> User:
    """The account of a registry row: sign it up through the real flow when it has none."""
    if registry.claimed_by_id:
        return registry.claimed_by
    registry_service.issue_activation_codes(
        IdRegistry.objects.filter(pk=registry.pk), valid_days=1, actor=actor
    )
    secret = twofactor.new_secret()
    done = signup.complete(
        registry.pk,
        username=username,
        password_hash=signup.hash_password(password),
        secret=secret,
        code=twofactor.current_code(secret),
    )
    if done is None:
        raise ValidationError(_("The demo authenticator code was refused. Run the command again."))
    user = done[0]
    user.nickname = c.NICKNAMES[username]
    user.totp_last_step = 0  # the first code is usable at once, not only from the next step
    user.save(update_fields=["nickname", "totp_last_step"])
    return user


def _teachers(structure: Structure, actor, password) -> tuple[dict, dict[str, User]]:
    """The teacher profiles by key, and the login accounts (head and demo teacher) by key."""
    profiles, logins = {}, {}
    for spec in c.TEACHERS:
        department = structure.departments[spec.department]
        head = {"is_hod": True, "hod_department": department} if spec.key == "hod" else {}
        registry, _created = _register(
            IdType.TEACHER,
            spec.external_id,
            spec.full_name,
            department,
            {"designation": spec.designation, **head},
            actor,
        )
        profiles[spec.key] = registry.teacher_profile
        if spec.key in c.LOGIN_KEYS:
            logins[spec.key] = _login_for(registry, c.LOGIN_KEYS[spec.key], password, actor)
    return profiles, logins


def _students(structure: Structure, department, ids, names, levels, actor):
    """The students of one department; returns their profiles and the rows created now."""
    profiles, new_rows = [], []
    for external_id, name, level in zip(ids, names, levels, strict=True):
        registry, created = _register(
            IdType.STUDENT,
            external_id,
            name,
            structure.departments[department],
            {
                "program": structure.programs[department],
                "batch": structure.batches[department],
                "level_term": structure.level_terms[level],
            },
            actor,
        )
        profiles.append(registry.student_profile)
        if created:
            new_rows.append(registry)
    return profiles, new_rows


def build(structure: Structure, actor: User, password: str | None) -> Cast:
    """Create whatever of the cast is missing and return all of it."""
    teachers, logins = _teachers(structure, actor, password)
    cse, cse_new = _students(
        structure, c.CSE, c.CSE_STUDENT_IDS, c.CSE_STUDENT_NAMES, CSE_LEVELS, actor
    )
    eee, eee_new = _students(
        structure, c.EEE, c.EEE_STUDENT_IDS, c.EEE_STUDENT_NAMES, EEE_LEVELS, actor
    )
    student = _login_for(cse[0].registry, c.STUDENT, password, actor)
    unclaimed = [row.pk for row in [*cse_new, *eee_new] if row.pk != student.registry.pk]
    issued = registry_service.issue_activation_codes(
        IdRegistry.objects.filter(pk__in=unclaimed), valid_days=c.CODE_VALID_DAYS, actor=actor
    )
    spare_ids = set(c.CSE_STUDENT_IDS[-c.SPARE_STUDENTS :])
    spares = tuple(
        (item.registry.external_id, item.code)
        for item in issued
        if item.registry.external_id in spare_ids
    )
    return Cast(actor, logins["hod"], logins["demo"], student, teachers, cse, eee, spares)

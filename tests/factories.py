"""Builders for identity and academic fixtures."""

import itertools
import time

import factory

from apps.academics.models import Batch, Department, LevelTerm, Program
from apps.accounts.models import (
    IdRegistry,
    IdType,
    RegistryStatus,
    StudentProfile,
    TeacherProfile,
    User,
)
from apps.core.permissions import Role
from apps.core.services.sessions import LANGUAGE_KEY, SECOND_FACTOR_KEY

PASSWORD = "Long-enough-pass-1"
_sequence = itertools.count(1)


class DepartmentFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Department

    code = factory.Sequence(lambda n: f"D{n:03d}")
    name = factory.Sequence(lambda n: f"Department {n}")


class ProgramFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Program

    department = factory.SubFactory(DepartmentFactory)
    code = factory.Sequence(lambda n: f"P{n:03d}")
    name = factory.Sequence(lambda n: f"Program {n}")


class BatchFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Batch

    program = factory.SubFactory(ProgramFactory)
    name = factory.Sequence(lambda n: f"Batch {n}")


class LevelTermFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = LevelTerm

    level = factory.Sequence(lambda n: n + 10)  # clear of the levels tests ask for by number
    term = 1
    order = factory.Sequence(lambda n: n + 1)


def make_student(department=None, external_id=None, full_name="Rahim Uddin") -> StudentProfile:
    """A pre-registered student (registry row + profile), not yet signed up."""
    department = department or DepartmentFactory()
    registry = IdRegistry.objects.create(
        id_type=IdType.STUDENT,
        external_id=external_id or f"2101{next(_sequence):04d}",
        full_name=full_name,
        department=department,
    )
    return StudentProfile.objects.create(
        registry=registry,
        program=ProgramFactory(department=department),
        level_term=LevelTermFactory(),
    )


def make_teacher(department=None, external_id=None, full_name="Karim Sir") -> TeacherProfile:
    department = department or DepartmentFactory()
    registry = IdRegistry.objects.create(
        id_type=IdType.TEACHER,
        external_id=external_id or f"T{next(_sequence):05d}",
        full_name=full_name,
        department=department,
    )
    return TeacherProfile.objects.create(registry=registry, designation="Lecturer")


def make_user(username: str, role: str, password: str = PASSWORD, **fields) -> User:
    """A user with a fixed username (the manager always issues a random one)."""
    user = User(username=username, role=role, **fields)
    user.set_password(password)
    user.save()
    return user


def claim(profile, password=None, **user_fields) -> User:
    """Sign the profile's registry row up: create its account and mark the row claimed.

    Accounts get no usable password unless asked: Argon2 is slow and tests log in with
    ``force_login``."""
    registry = profile.registry
    role = Role.STUDENT if registry.id_type == IdType.STUDENT else Role.TEACHER
    user = User.objects.create_user(role, password, department=registry.department, **user_fields)
    registry.claimed_by = user
    registry.status = RegistryStatus.CLAIMED
    registry.save()
    return user


def make_hod(department=None) -> User:
    """A signed-up teacher heading ``department``."""
    department = department or DepartmentFactory()
    profile = make_teacher(department)
    user = claim(profile)
    profile.is_hod = True
    profile.hod_department = department
    profile.save()
    return User.objects.get(pk=user.pk)


def make_admin(password=None, **fields) -> User:
    return User.objects.create_admin(password, **fields)


def sign_in(client, user: User) -> None:
    """Log ``user`` in as if they had also passed the second factor (see ``sessions.problem``)."""
    client.force_login(user)
    session = client.session
    session[SECOND_FACTOR_KEY] = int(time.time())
    # Tests pick their own language; the saved-language cookie is tested through real logins.
    session.pop(LANGUAGE_KEY, None)
    session.save()

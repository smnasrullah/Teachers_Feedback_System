import io
import re

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, connection, transaction

from apps.accounts.models import (
    EMAIL_INDEX_PURPOSE,
    IdRegistry,
    IdType,
    RegistryStatus,
    TeacherProfile,
    User,
    registry_index,
)
from apps.accounts.services.identifiers import (
    clean_registry_id,
    normalize_activation_code,
    normalize_phone,
    normalize_registry_id,
)
from apps.accounts.services.username import ALPHABET, PREFIXES, generate_username
from apps.core.encryption import blind_index
from apps.core.permissions import HOD, Role, user_roles
from tests.factories import (
    DepartmentFactory,
    claim,
    make_admin,
    make_hod,
    make_student,
    make_teacher,
    make_user,
)

pytestmark = pytest.mark.django_db


def raw_value(table, column, pk):
    with connection.cursor() as cursor:
        cursor.execute(f"SELECT {column} FROM {table} WHERE id = %s", [pk])  # noqa: S608
        return cursor.fetchone()[0]


# --- usernames -------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("role", "prefix"),
    [(Role.STUDENT, "stu"), (Role.TEACHER, "tch"), (Role.ADMIN, "adm")],
)
def test_username_is_prefixed_random_and_well_formed(role, prefix):
    user = User.objects.create_user(role, "Long-enough-pass-1")
    assert re.fullmatch(rf"{prefix}_[{ALPHABET}]{{6}}", user.username)
    assert user.role == role


def test_every_role_has_a_prefix():
    assert set(PREFIXES) == set(Role.values)


def test_usernames_are_unique_across_many_accounts():
    names = {User.objects.create_user(Role.STUDENT).username for _ in range(60)}
    assert len(names) == 60


def test_generate_username_skips_a_taken_name(monkeypatch):
    taken = make_user("stu_aaaaaa", Role.STUDENT)
    candidates = iter("aaaaaa" + "bbbbbb")
    monkeypatch.setattr(
        "apps.accounts.services.username.secrets.choice", lambda _alphabet: next(candidates)
    )
    assert generate_username(Role.STUDENT) == "stu_bbbbbb"
    assert taken.username == "stu_aaaaaa"


def test_username_cannot_be_changed():
    user = User.objects.create_user(Role.STUDENT)
    original = user.username
    user.username = "stu_hacked"
    with pytest.raises(ValueError, match="never changes"):
        user.save()
    fresh = User.objects.get(pk=user.pk)
    assert fresh.username == original
    fresh.nickname = "Rafi"
    fresh.save()  # other fields stay editable
    fresh.username = "stu_other1"
    with pytest.raises(ValueError, match="never changes"):
        fresh.save()


def test_username_column_is_unique():
    make_user("stu_dup001", Role.STUDENT)
    with pytest.raises(IntegrityError), transaction.atomic():
        make_user("stu_dup001", Role.TEACHER)


# --- encryption at rest ----------------------------------------------------------------


def test_registry_id_and_name_are_stored_encrypted():
    student = make_student(external_id="2101001", full_name="Rahim Uddin")
    registry = student.registry
    for column, plaintext in (("external_id", "2101001"), ("full_name", "Rahim Uddin")):
        raw = raw_value("accounts_idregistry", column, registry.pk)
        assert raw != plaintext
        assert plaintext not in raw
    reloaded = IdRegistry.objects.get(pk=registry.pk)
    assert (reloaded.external_id, reloaded.full_name) == ("2101001", "Rahim Uddin")
    assert raw_value("accounts_idregistry", "external_id_index", registry.pk) != "2101001"


def test_user_contacts_and_totp_secret_are_stored_encrypted():
    user = User.objects.create_user(
        Role.TEACHER,
        contact_email="Teacher@Example.edu",
        contact_phone="01712345678",
        totp_secret="JBSWY3DPEHPK3PXP",
    )
    for column, plaintext in (
        ("contact_email", "Teacher@Example.edu"),
        ("contact_phone", "+8801712345678"),
        ("totp_secret", "JBSWY3DPEHPK3PXP"),
    ):
        raw = raw_value("accounts_user", column, user.pk)
        assert plaintext not in raw
    reloaded = User.objects.get(pk=user.pk)
    assert reloaded.contact_phone == "+8801712345678"
    assert reloaded.totp_secret == "JBSWY3DPEHPK3PXP"


def test_contact_blind_indexes_are_case_insensitive_and_unique():
    first = User.objects.create_user(Role.STUDENT, contact_email="Mix@Example.edu")
    assert first.contact_email_index == User.objects.get(pk=first.pk).contact_email_index
    with pytest.raises(IntegrityError), transaction.atomic():
        User.objects.create_user(Role.STUDENT, contact_email="mix@example.EDU")
    # Users without a contact do not collide on the (NULL) index.
    User.objects.create_user(Role.STUDENT)
    User.objects.create_user(Role.STUDENT)


def test_contact_index_follows_a_partial_update():
    user = User.objects.create_user(Role.STUDENT, contact_email="old@example.edu")
    user.contact_email = "new@example.edu"
    user.save(update_fields=["contact_email"])
    indexes = User.objects.filter(pk=user.pk).values_list("contact_email_index", flat=True)
    assert list(indexes) == [blind_index("new@example.edu", EMAIL_INDEX_PURPOSE)]


# --- identifier normalisation ----------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("2101001", "2101001"),
        (" ২১০১০০১ ", "2101001"),
        ("cse 21-007", "CSE21-007"),
        ("ｃｓｅ２１", "CSE21"),  # noqa: RUF001 - full-width forms are the point
    ],
)
def test_registry_ids_are_normalised(raw, expected):
    assert normalize_registry_id(raw) == expected


@pytest.mark.parametrize("raw", ["", "ab", "-2101", "21/01 001?", "x" * 40])
def test_clean_registry_id_rejects_malformed_ids(raw):
    with pytest.raises(ValidationError):
        clean_registry_id(raw)


def test_equivalent_spellings_share_one_index_and_one_row():
    make_student(external_id="2101001")
    assert registry_index("২১০১০০১") == registry_index(" 2101001 ")
    with pytest.raises(IntegrityError), transaction.atomic():
        IdRegistry.objects.create(
            id_type=IdType.STUDENT, external_id="২১০১০০১", department=DepartmentFactory()
        )


def test_same_id_may_exist_once_per_type():
    make_student(external_id="9900")
    make_teacher(external_id="9900")
    assert IdRegistry.objects.filter(external_id_index=registry_index("9900")).count() == 2


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("01712345678", "+8801712345678"),
        ("+880 1712-345678", "+8801712345678"),
        ("০১৭১২৩৪৫৬৭৮", "+8801712345678"),
        ("8801712345678", "+8801712345678"),
        ("", ""),
    ],
)
def test_phone_numbers_are_normalised(raw, expected):
    assert normalize_phone(raw) == expected


def test_activation_codes_ignore_case_and_separators():
    assert normalize_activation_code("abcd-efgh 2345") == "ABCDEFGH2345"


# --- registry and profile invariants ---------------------------------------------------


def test_unclaimed_entry_cannot_name_an_account():
    student = make_student()
    student.registry.claimed_by = User.objects.create_user(Role.STUDENT)
    with pytest.raises(IntegrityError), transaction.atomic():
        student.registry.save()


def test_claimed_entry_needs_an_account():
    student = make_student()
    student.registry.status = RegistryStatus.CLAIMED
    with pytest.raises(IntegrityError), transaction.atomic():
        student.registry.save()


def test_profiles_exist_before_signup():
    student, teacher = make_student(), make_teacher()
    assert student.registry.claimed_by is None and teacher.registry.claimed_by is None
    assert student.registry.student_profile == student
    assert teacher.registry.teacher_profile == teacher


# --- head of department ----------------------------------------------------------------


def test_only_one_hod_per_department():
    department = DepartmentFactory()
    make_hod(department)
    second = make_teacher(department)
    second.is_hod, second.hod_department = True, department
    with pytest.raises(IntegrityError), transaction.atomic():
        second.save()


def test_hods_of_different_departments_coexist():
    assert make_hod().is_hod and make_hod().is_hod


def test_hod_flag_and_department_must_agree():
    teacher = make_teacher()
    teacher.is_hod = True
    with pytest.raises(IntegrityError), transaction.atomic():
        teacher.save()
    teacher.is_hod, teacher.hod_department = False, DepartmentFactory()
    with pytest.raises(IntegrityError), transaction.atomic():
        teacher.save()


def test_user_exposes_hod_flag_and_department():
    department = DepartmentFactory()
    hod = make_hod(department)
    assert hod.is_hod
    assert hod.hod_department == department
    assert hod.hod_department_id == department.pk
    assert user_roles(hod) == {Role.TEACHER, HOD}


def test_plain_teacher_student_and_admin_are_not_hods():
    teacher = claim(make_teacher())
    student = claim(make_student())
    for user in (teacher, student, make_admin()):
        assert not user.is_hod
        assert user.hod_department is None
        assert user.hod_department_id is None
        assert HOD not in user_roles(user)


def test_a_hod_who_becomes_admin_stops_being_hod():
    hod = make_hod()
    hod.role = Role.ADMIN
    assert not hod.is_hod
    assert user_roles(hod) == {Role.ADMIN}


def test_refresh_from_db_clears_the_cached_profile():
    hod = make_hod()
    assert hod.is_hod
    TeacherProfile.objects.filter(pk=hod.teacher_profile.pk).update(
        is_hod=False, hod_department=None
    )
    assert hod.is_hod  # cached until refreshed
    hod.refresh_from_db()
    assert not hod.is_hod


def test_key_rotation_covers_every_encrypted_identity_column():
    from apps.core.services.keys import encrypted_models

    covered = {model._meta.label: set(names) for model, names in encrypted_models()}
    assert covered["accounts.IdRegistry"] == {"external_id", "full_name"}
    assert covered["accounts.User"] == {"contact_email", "contact_phone", "totp_secret"}


def test_key_rotation_keeps_identity_data_readable():
    from django.core.management import call_command

    student = make_student(external_id="2101123", full_name="Mina Rahman")
    user = User.objects.create_user(Role.STUDENT, contact_email="mina@example.edu")
    call_command("rotate_encryption_keys", stdout=io.StringIO())
    assert IdRegistry.objects.get(pk=student.registry.pk).external_id == "2101123"
    assert User.objects.get(pk=user.pk).contact_email == "mina@example.edu"

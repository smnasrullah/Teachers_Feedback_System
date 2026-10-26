import json
from datetime import timedelta

import pytest
from django.core.exceptions import ValidationError
from django.db import connection
from django.utils import timezone

from apps.accounts.models import IdRegistry, IdType, RegistryStatus, TeacherProfile, User
from apps.accounts.services import registry as registry_service
from apps.accounts.services import roles
from apps.accounts.services.activation import generate_code, hash_code
from apps.auditlog.models import AuditEvent
from apps.core.models import ActiveSession
from apps.core.permissions import Role
from tests.factories import (
    BatchFactory,
    DepartmentFactory,
    LevelTermFactory,
    ProgramFactory,
    claim,
    make_admin,
    make_hod,
    make_student,
    make_teacher,
)

pytestmark = pytest.mark.django_db


@pytest.fixture
def admin():
    return make_admin()


def student_profile_values(department):
    program = ProgramFactory(department=department)
    return {
        "program": program,
        "batch": BatchFactory(program=program),
        "level_term": LevelTermFactory(),
        "section": "A",
        "academic_status": "active",
    }


# --- create / update -------------------------------------------------------------------


def test_register_creates_registry_and_profile_together(admin):
    department = DepartmentFactory()
    entry = registry_service.register(
        IdType.STUDENT,
        external_id=" ২১০১০০১ ",
        full_name="Rahim Uddin",
        department=department,
        profile=student_profile_values(department),
        actor=admin,
    )
    assert entry.external_id == "2101001"
    assert entry.status == RegistryStatus.UNCLAIMED and entry.claimed_by is None
    assert entry.student_profile.section == "A"


def test_register_rejects_a_duplicate_in_any_spelling(admin):
    department = DepartmentFactory()
    make_student(department, external_id="2101001")
    with pytest.raises(ValidationError) as caught:
        registry_service.register(
            IdType.STUDENT,
            external_id="২১০১ ০০১",
            full_name="",
            department=department,
            profile=student_profile_values(department),
            actor=admin,
        )
    assert caught.value.code == "duplicate_id"
    assert IdRegistry.objects.filter(id_type=IdType.STUDENT).count() == 1


def test_register_rejects_a_malformed_id(admin):
    department = DepartmentFactory()
    with pytest.raises(ValidationError):
        registry_service.register(
            IdType.TEACHER,
            external_id="!!",
            full_name="",
            department=department,
            profile={"designation": ""},
            actor=admin,
        )


def test_update_changes_fields_and_follows_the_account_department(admin):
    old, new = DepartmentFactory(), DepartmentFactory()
    student = make_student(old)
    account = claim(student)
    values = student_profile_values(new)
    changed = registry_service.update(
        student.registry,
        external_id=student.registry.external_id,
        full_name="New Name",
        department=new,
        profile=values,
        actor=admin,
    )
    assert {"full_name", "department", "program", "section"} <= set(changed)
    account.refresh_from_db()
    assert account.department == new
    event = AuditEvent.objects.get(action="registry.updated")
    assert event.department_id == new.pk
    assert "New Name" not in json.dumps(event.metadata)


def test_update_cannot_change_the_id_of_a_claimed_entry(admin):
    student = make_student()
    claim(student)
    with pytest.raises(ValidationError) as caught:
        registry_service.update(
            student.registry,
            external_id="9999999",
            full_name="",
            department=student.registry.department,
            profile=student_profile_values(student.registry.department),
            actor=admin,
        )
    assert caught.value.code == "claimed_id"


def test_update_can_change_the_id_of_an_unclaimed_entry_but_not_to_a_taken_one(admin):
    department = DepartmentFactory()
    student = make_student(department, external_id="1000001")
    make_student(department, external_id="1000002")
    profile = student_profile_values(department)

    def attempt(new_id):
        return registry_service.update(
            student.registry,
            external_id=new_id,
            full_name="",
            department=department,
            profile=profile,
            actor=admin,
        )

    with pytest.raises(ValidationError):
        attempt("1000002")
    assert "external_id" in attempt("1000009")
    student.registry.refresh_from_db()
    assert student.registry.external_id == "1000009"


def test_unchanged_update_writes_no_audit_event(admin):
    student = make_student()
    registry_service.update(
        student.registry,
        external_id=student.registry.external_id,
        full_name=student.registry.full_name,
        department=student.registry.department,
        profile={
            name: getattr(student, name)
            for name in ("program", "batch", "level_term", "section", "academic_status")
        },
        actor=admin,
    )
    assert not AuditEvent.objects.filter(action="registry.updated").exists()


# --- activation codes ------------------------------------------------------------------


def all_stored_text(model):
    """Every value of every column of every row, as text (decrypted where applicable)."""
    return json.dumps(list(model.objects.values()), default=str)


def test_issued_codes_are_stored_only_as_a_keyed_hash(admin):
    students = [make_student() for _ in range(3)]
    entries = IdRegistry.objects.filter(pk__in=[s.registry.pk for s in students])
    issued = registry_service.issue_activation_codes(entries, valid_days=7, actor=admin)
    assert len(issued) == 3
    for item in issued:
        item.registry.refresh_from_db()
        assert item.registry.activation_code_hash == hash_code(item.code)
        assert item.registry.activation_code_hash != item.code
        assert len(item.code.replace("-", "")) == 12
        assert item.registry.activation_expires_at > timezone.now() + timedelta(days=6)
        assert item.registry.activation_used_at is None
    stored = all_stored_text(IdRegistry)
    with connection.cursor() as cursor:  # also the raw rows, whatever the ORM hides
        cursor.execute("SELECT * FROM accounts_idregistry")
        stored += json.dumps(cursor.fetchall(), default=str)
    for item in issued:
        assert item.code not in stored
        assert item.code.replace("-", "") not in stored
    assert len({item.code for item in issued}) == 3


def test_codes_are_audited_without_the_codes_or_ids(admin):
    student = make_student(external_id="2101555")
    registry_service.issue_activation_codes(
        IdRegistry.objects.filter(pk=student.registry.pk), valid_days=3, actor=admin
    )
    event = AuditEvent.objects.get(action="registry.codes_issued")
    assert event.metadata == {"count": 1, "valid_days": 3, "registry_ids": [student.registry.pk]}
    assert event.department_id == student.registry.department_id


def test_only_unclaimed_entries_receive_codes(admin):
    unclaimed, claimed, revoked = make_student(), make_student(), make_student()
    claim(claimed)
    registry_service.revoke(IdRegistry.objects.filter(pk=revoked.registry.pk), actor=admin)
    issued = registry_service.issue_activation_codes(
        IdRegistry.objects.all(), valid_days=7, actor=admin
    )
    assert [item.registry.pk for item in issued] == [unclaimed.registry.pk]


def test_issuing_again_replaces_the_previous_code(admin):
    student = make_student()
    entries = IdRegistry.objects.filter(pk=student.registry.pk)
    (first,) = registry_service.issue_activation_codes(entries, valid_days=7, actor=admin)
    (second,) = registry_service.issue_activation_codes(entries, valid_days=7, actor=admin)
    student.registry.refresh_from_db()
    assert student.registry.activation_code_hash == hash_code(second.code)
    assert student.registry.activation_code_hash != hash_code(first.code)


def test_generated_codes_use_the_unambiguous_alphabet():
    for _ in range(50):
        code = generate_code()
        assert len(code) == 14 and code[4] == code[9] == "-"
        assert not set(code.replace("-", "")) & set("01OIl")


def test_codes_must_not_be_blank():
    with pytest.raises(ValueError):
        hash_code(" - ")


# --- revoke / re-activate --------------------------------------------------------------


def test_revoking_an_unclaimed_entry_voids_its_code(admin):
    student = make_student()
    entries = IdRegistry.objects.filter(pk=student.registry.pk)
    registry_service.issue_activation_codes(entries, valid_days=7, actor=admin)
    assert registry_service.revoke(entries, actor=admin) == 1
    student.registry.refresh_from_db()
    assert student.registry.status == RegistryStatus.REVOKED
    assert student.registry.activation_code_hash == ""
    assert student.registry.activation_expires_at is None
    assert registry_service.revoke(entries, actor=admin) == 0  # idempotent


def test_revoking_a_claimed_entry_disables_the_account_and_signs_it_out(admin):
    student = make_student()
    account = claim(student)
    ActiveSession.objects.create(user=account, login_id="abc")
    registry_service.revoke(IdRegistry.objects.filter(pk=student.registry.pk), actor=admin)
    account.refresh_from_db()
    assert account.is_active is False
    assert not ActiveSession.objects.filter(user=account).exists()
    student.registry.refresh_from_db()
    assert student.registry.claimed_by == account


def test_activating_restores_the_previous_state(admin):
    claimed, unclaimed = make_student(), make_student()
    account = claim(claimed)
    entries = IdRegistry.objects.filter(pk__in=[claimed.registry.pk, unclaimed.registry.pk])
    registry_service.revoke(entries, actor=admin)
    assert registry_service.activate(entries, actor=admin) == 2
    claimed.registry.refresh_from_db()
    unclaimed.registry.refresh_from_db()
    account.refresh_from_db()
    assert claimed.registry.status == RegistryStatus.CLAIMED and account.is_active
    assert unclaimed.registry.status == RegistryStatus.UNCLAIMED


def test_an_admin_cannot_revoke_their_own_entry():
    teacher = make_teacher()
    account = claim(teacher)
    account.role = Role.ADMIN
    account.save()
    with pytest.raises(ValidationError) as caught:
        registry_service.revoke(IdRegistry.objects.filter(pk=teacher.registry.pk), actor=account)
    assert caught.value.code == "revoke_self"


def test_bulk_size_is_capped(admin, monkeypatch):
    monkeypatch.setattr(registry_service, "MAX_BULK_ROWS", 2)
    for _ in range(3):
        make_student()
    with pytest.raises(ValidationError) as caught:
        registry_service.revoke(IdRegistry.objects.all(), actor=admin)
    assert caught.value.code == "too_many"
    assert not IdRegistry.objects.filter(status=RegistryStatus.REVOKED).exists()


def test_status_audit_events_hold_ids_and_counts_only(admin):
    students = [make_student(external_id=f"77700{i}") for i in range(2)]
    entries = IdRegistry.objects.filter(pk__in=[s.registry.pk for s in students])
    registry_service.revoke(entries, actor=admin)
    registry_service.activate(entries, actor=admin)
    for action in ("registry.revoked", "registry.activated"):
        event = AuditEvent.objects.get(action=action)
        assert event.metadata["count"] == 2
        assert "77700" not in json.dumps(event.metadata)


# --- roles and HOD ---------------------------------------------------------------------


def test_teacher_can_become_admin_and_back(admin):
    teacher = claim(make_teacher())
    assert roles.change_role(teacher, Role.ADMIN, actor=admin) is True
    teacher.refresh_from_db()
    assert teacher.role == Role.ADMIN
    assert roles.change_role(teacher, Role.TEACHER, actor=admin) is True
    assert roles.change_role(teacher, Role.TEACHER, actor=admin) is False
    event = AuditEvent.objects.filter(action="user.role_changed").first()
    assert event.metadata == {"from": "teacher", "to": "admin"}


def test_making_a_hod_an_admin_removes_the_hod_flag(admin):
    hod = make_hod()
    roles.change_role(hod, Role.ADMIN, actor=admin)
    profile = TeacherProfile.objects.get(pk=hod.teacher_profile.pk)
    assert profile.is_hod is False and profile.hod_department is None


@pytest.mark.parametrize(
    ("make_target", "new_role", "code"),
    [
        (lambda: claim(make_student()), Role.ADMIN, "role_fixed"),
        (lambda: claim(make_teacher()), Role.STUDENT, "role_fixed"),
        (lambda: make_admin(), Role.TEACHER, "role_needs_teacher_id"),
    ],
)
def test_forbidden_role_changes(admin, make_target, new_role, code):
    target = make_target()
    with pytest.raises(ValidationError) as caught:
        roles.change_role(target, new_role, actor=admin)
    assert caught.value.code == code
    assert User.objects.get(pk=target.pk).role == target.role


def test_an_admin_cannot_change_their_own_role(admin):
    with pytest.raises(ValidationError) as caught:
        roles.change_role(admin, Role.TEACHER, actor=admin)
    assert caught.value.code == "role_self"


def test_assigning_a_hod_replaces_the_current_one(admin):
    department = DepartmentFactory()
    old = make_hod(department)
    newcomer = make_teacher(department)
    replaced = roles.assign_hod(newcomer, department, actor=admin)
    assert replaced.pk == old.teacher_profile.pk
    heads = TeacherProfile.objects.filter(is_hod=True, hod_department=department)
    assert [head.pk for head in heads] == [newcomer.pk]
    actions = list(AuditEvent.objects.order_by("id").values_list("action", flat=True))
    assert actions == ["hod.removed", "hod.assigned"]


def test_moving_a_hod_to_another_department(admin):
    first, second = DepartmentFactory(), DepartmentFactory()
    hod = make_hod(first)
    roles.assign_hod(hod.teacher_profile, second, actor=admin)
    profile = TeacherProfile.objects.get(pk=hod.teacher_profile.pk)
    assert profile.hod_department == second
    assert not TeacherProfile.objects.filter(is_hod=True, hod_department=first).exists()


def test_removing_a_hod(admin):
    hod = make_hod()
    assert roles.remove_hod(hod.teacher_profile, actor=admin) is True
    assert roles.remove_hod(hod.teacher_profile, actor=admin) is False
    hod.refresh_from_db()
    assert not hod.is_hod


def test_revoked_teachers_and_non_teacher_accounts_cannot_be_hod(admin):
    department = DepartmentFactory()
    revoked = make_teacher(department)
    registry_service.revoke(IdRegistry.objects.filter(pk=revoked.registry.pk), actor=admin)
    with pytest.raises(ValidationError) as caught:
        roles.assign_hod(revoked, department, actor=admin)
    assert caught.value.code == "hod_ineligible"

    promoted = make_teacher(department)
    roles.change_role(claim(promoted), Role.ADMIN, actor=admin)
    with pytest.raises(ValidationError) as caught:
        roles.assign_hod(promoted, department, actor=admin)
    assert caught.value.code == "hod_not_teacher"


def test_a_teacher_can_be_made_hod_before_signing_up(admin):
    department = DepartmentFactory()
    teacher = make_teacher(department)
    roles.assign_hod(teacher, department, actor=admin)
    account = claim(teacher)
    assert User.objects.get(pk=account.pk).is_hod

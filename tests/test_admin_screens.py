import csv
import io
import json

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from apps.accounts.models import IdRegistry, RegistryStatus, TeacherProfile, User
from apps.accounts.services.activation import hash_code
from apps.auditlog.models import AuditEvent
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

SECRET_ID = "2101999"
SECRET_NAME = "Tahmina Akter"


@pytest.fixture
def admin_client(client):
    client.defaults["HTTP_ACCEPT_LANGUAGE"] = "en"  # the site default is Bangla
    client.force_login(make_admin())
    return client


@pytest.fixture
def secret_student():
    return make_student(external_id=SECRET_ID, full_name=SECRET_NAME)


def urls_for(registry, account):
    return [
        reverse("accounts:registry_list"),
        reverse("accounts:registry_create", args=["student"]),
        reverse("accounts:registry_create", args=["teacher"]),
        reverse("accounts:registry_edit", args=[registry.pk]),
        reverse("accounts:user_list"),
        reverse("accounts:user_detail", args=[account.pk]),
    ]


def post_urls_for(registry, account):
    return [
        reverse("accounts:registry_bulk"),
        reverse("accounts:registry_hod", args=[registry.pk]),
        reverse("accounts:user_role", args=[account.pk]),
    ]


# --- access control --------------------------------------------------------------------


def test_anonymous_users_are_sent_to_login(client, secret_student):
    account = claim(make_teacher())
    for url in urls_for(secret_student.registry, account):
        response = client.get(url)
        assert response.status_code == 302 and "login" in response["Location"]
    for url in post_urls_for(secret_student.registry, account):
        assert client.post(url).status_code == 302


@pytest.mark.parametrize("role", ["student", "teacher", "hod"])
def test_only_admins_reach_the_management_screens(client, secret_student, role):
    department = secret_student.registry.department
    viewer = {
        "student": lambda: claim(make_student(department)),
        "teacher": lambda: claim(make_teacher(department)),
        "hod": lambda: make_hod(department),  # even the HOD of the student's own department
    }[role]()
    client.force_login(viewer)
    for url in urls_for(secret_student.registry, viewer):
        response = client.get(url)
        assert response.status_code == 403
        assert SECRET_ID.encode() not in response.content
        assert SECRET_NAME.encode() not in response.content
    for url in post_urls_for(secret_student.registry, viewer):
        assert (
            client.post(url, {"action": "revoke", "ids": [secret_student.registry.pk]}).status_code
            == 403
        )
    secret_student.registry.refresh_from_db()
    assert secret_student.registry.status == RegistryStatus.UNCLAIMED


def test_admin_sees_every_screen(admin_client, secret_student):
    account = claim(make_teacher())
    for url in urls_for(secret_student.registry, account):
        assert admin_client.get(url).status_code == 200


def test_unknown_entry_type_and_ids_are_404(admin_client):
    assert admin_client.get(reverse("accounts:registry_create", args=["alien"])).status_code == 404
    assert admin_client.get(reverse("accounts:registry_edit", args=[999999])).status_code == 404
    assert admin_client.get(reverse("accounts:user_detail", args=[999999])).status_code == 404


def test_state_changing_screens_reject_get(admin_client, secret_student):
    for name in ("registry_bulk",):
        assert admin_client.get(reverse(f"accounts:{name}")).status_code == 405
    assert (
        admin_client.get(
            reverse("accounts:registry_hod", args=[secret_student.registry.pk])
        ).status_code
        == 405
    )


# --- registry list ---------------------------------------------------------------------


def test_list_shows_entries_and_filters(admin_client, secret_student):
    make_teacher(external_id="T77777")
    url = reverse("accounts:registry_list")
    body = admin_client.get(url).content.decode()
    assert SECRET_ID in body and "T77777" in body
    only_students = admin_client.get(url, {"id_type": "student"}).content.decode()
    assert SECRET_ID in only_students and "T77777" not in only_students


def test_list_searches_by_exact_id_in_any_spelling_and_by_username(admin_client, secret_student):
    make_student(external_id="2100001")
    url = reverse("accounts:registry_list")
    found = admin_client.get(url, {"q": " ২১০১৯৯৯ "}).content.decode()
    assert SECRET_ID in found and "2100001" not in found
    partial = admin_client.get(url, {"q": "21019"}).content.decode()
    assert SECRET_ID not in partial  # exact match only: no ID enumeration by prefix
    account = claim(make_student(external_id="2100002"))
    by_name = admin_client.get(url, {"q": account.username.upper()}).content.decode()
    assert "2100002" in by_name and SECRET_ID not in by_name


def test_list_query_count_does_not_grow_with_rows(admin_client):
    department = DepartmentFactory()
    make_student(department)
    url = reverse("accounts:registry_list")
    admin_client.get(url)  # warm caches

    with CaptureQueriesContext(connection) as few:
        admin_client.get(url)
    for _ in range(25):
        claim(make_student(department))
    with CaptureQueriesContext(connection) as many:
        admin_client.get(url)
    assert len(many) == len(few)


def test_list_paginates(admin_client):
    department = DepartmentFactory()
    for _ in range(55):
        make_student(department)
    url = reverse("accounts:registry_list")
    assert admin_client.get(url).content.decode().count('name="ids"') == 50
    assert admin_client.get(url, {"page": 2}).content.decode().count('name="ids"') == 5


# --- create / edit ---------------------------------------------------------------------


def student_form(department, **overrides):
    program = ProgramFactory(department=department)
    data = {
        "external_id": "2102001",
        "full_name": "Sabbir Hossain",
        "department": department.pk,
        "program": program.pk,
        "batch": BatchFactory(program=program).pk,
        "level_term": LevelTermFactory().pk,
        "section": "B",
        "academic_status": "active",
    }
    return {**data, **overrides}


def test_admin_creates_a_student(admin_client):
    department = DepartmentFactory()
    response = admin_client.post(
        reverse("accounts:registry_create", args=["student"]), student_form(department)
    )
    assert response.status_code == 302
    entry = IdRegistry.objects.get()
    assert entry.external_id == "2102001" and entry.student_profile.section == "B"
    assert AuditEvent.objects.filter(action="registry.created").count() == 1


def test_create_rejects_duplicates_and_mismatched_structure(admin_client, secret_student):
    department = secret_student.registry.department
    url = reverse("accounts:registry_create", args=["student"])
    duplicate = admin_client.post(url, student_form(department, external_id="২১০১৯৯৯"))
    assert duplicate.status_code == 200
    assert "already registered" in duplicate.content.decode()

    other_department = DepartmentFactory()
    foreign_program = ProgramFactory(department=other_department)
    mismatched = admin_client.post(url, student_form(department, program=foreign_program.pk))
    assert mismatched.status_code == 200
    assert "different department" in mismatched.content.decode()
    assert IdRegistry.objects.count() == 1


def test_admin_creates_a_teacher_with_a_photo(admin_client, tmp_path, settings):
    from PIL import Image

    settings.MEDIA_ROOT = tmp_path
    department = DepartmentFactory()
    buffer = io.BytesIO()
    Image.new("RGB", (30, 30), "green").save(buffer, format="PNG")
    buffer.seek(0)
    buffer.name = "me.png"
    response = admin_client.post(
        reverse("accounts:registry_create", args=["teacher"]),
        {
            "external_id": "T10001",
            "full_name": "Dr. Salma",
            "department": department.pk,
            "designation": "Professor",
            "photo": buffer,
        },
    )
    assert response.status_code == 302
    profile = TeacherProfile.objects.get()
    assert profile.designation == "Professor"
    assert profile.photo.name.startswith("teachers/") and profile.photo.name.endswith(".webp")
    assert "me" not in profile.photo.name.split("/")[-1]


def test_teacher_photo_that_is_not_an_image_is_refused(admin_client, tmp_path, settings):
    from django.core.files.uploadedfile import SimpleUploadedFile

    settings.MEDIA_ROOT = tmp_path
    response = admin_client.post(
        reverse("accounts:registry_create", args=["teacher"]),
        {
            "external_id": "T10002",
            "department": DepartmentFactory().pk,
            "photo": SimpleUploadedFile("shell.png", b"<?php evil(); ?>", "image/png"),
        },
    )
    assert response.status_code == 200
    assert "valid JPEG, PNG or WebP" in response.content.decode()
    assert not IdRegistry.objects.exists() and not list(tmp_path.iterdir())


def test_edit_form_is_prefilled_and_saves(admin_client, secret_student):
    url = reverse("accounts:registry_edit", args=[secret_student.registry.pk])
    page = admin_client.get(url).content.decode()
    assert SECRET_ID in page and SECRET_NAME in page
    department = secret_student.registry.department
    response = admin_client.post(
        url,
        student_form(
            department,
            external_id=SECRET_ID,
            full_name="Tahmina A. Khan",
            program=secret_student.program.pk,
            batch="",
            level_term=secret_student.level_term.pk,
        ),
    )
    assert response.status_code == 302
    secret_student.registry.refresh_from_db()
    assert secret_student.registry.full_name == "Tahmina A. Khan"


def test_claimed_id_field_is_locked_in_the_form(admin_client, secret_student):
    claim(secret_student)
    url = reverse("accounts:registry_edit", args=[secret_student.registry.pk])
    department = secret_student.registry.department
    admin_client.post(
        url,
        student_form(
            department,
            external_id="1111111",
            program=secret_student.program.pk,
            level_term=secret_student.level_term.pk,
        ),
    )
    secret_student.registry.refresh_from_db()
    assert secret_student.registry.external_id == SECRET_ID


# --- bulk actions and activation codes -------------------------------------------------


def bulk(client, action, entries, **extra):
    data = {"action": action, "ids": [entry.registry.pk for entry in entries], **extra}
    return client.post(reverse("accounts:registry_bulk"), data)


def test_generating_codes_downloads_a_csv_exactly_once(admin_client):
    students = [make_student(external_id=f"3300{i}") for i in range(3)]
    response = bulk(admin_client, "generate_codes", students, valid_days="10")

    assert response.status_code == 200
    assert response["Content-Type"].startswith("text/csv")
    assert response["Content-Disposition"].startswith('attachment; filename="activation-codes-')
    assert "no-store" in response["Cache-Control"]
    rows = list(csv.reader(io.StringIO(response.content.decode("utf-8-sig"))))
    header, body = rows[0], rows[1:]
    assert len(body) == 3 and len(header) == 5
    codes = {row[0]: row[3] for row in body}
    for student in students:
        student.registry.refresh_from_db()
        code = codes[student.registry.external_id]
        assert student.registry.activation_code_hash == hash_code(code)

    # Nothing afterwards (list, edit page, audit log) reveals a code.
    pages = [
        admin_client.get(reverse("accounts:registry_list")).content.decode(),
        admin_client.get(
            reverse("accounts:registry_edit", args=[students[0].registry.pk])
        ).content.decode(),
        json.dumps(list(AuditEvent.objects.values_list("metadata", flat=True))),
    ]
    for code in codes.values():
        assert all(code not in page and code.replace("-", "") not in page for page in pages)


def test_generating_codes_for_nothing_eligible_explains_why(admin_client):
    claimed = make_student()
    claim(claimed)
    response = bulk(admin_client, "generate_codes", [claimed], valid_days="10")
    assert response.status_code == 302
    follow = admin_client.get(response["Location"])
    assert "Only unclaimed entries" in follow.content.decode()


def test_valid_days_is_bounded(admin_client):
    student = make_student()
    response = bulk(admin_client, "generate_codes", [student], valid_days="9999")
    assert response.status_code == 302
    student.registry.refresh_from_db()
    assert student.registry.activation_code_hash == ""


def test_bulk_revoke_and_activate(admin_client):
    students = [make_student() for _ in range(2)]
    bulk(admin_client, "revoke", students)
    assert IdRegistry.objects.filter(status=RegistryStatus.REVOKED).count() == 2
    bulk(admin_client, "activate", students)
    assert IdRegistry.objects.filter(status=RegistryStatus.UNCLAIMED).count() == 2


def test_bulk_requires_a_selection_and_a_valid_action(admin_client):
    student = make_student()
    url = reverse("accounts:registry_bulk")
    for data in ({"action": "revoke"}, {"action": "explode", "ids": [student.registry.pk]}):
        assert admin_client.post(url, data).status_code == 302
    student.registry.refresh_from_db()
    assert student.registry.status == RegistryStatus.UNCLAIMED


def test_bulk_can_target_everything_matching_the_filters(admin_client):
    department, other = DepartmentFactory(), DepartmentFactory()
    inside = [make_student(department) for _ in range(3)]
    outside = make_student(other)
    response = admin_client.post(
        reverse("accounts:registry_bulk"),
        {
            "action": "revoke",
            "select_all_matching": "on",
            "department": department.pk,
            "return_query": f"department={department.pk}",
        },
    )
    assert response["Location"] == f"{reverse('accounts:registry_list')}?department={department.pk}"
    assert IdRegistry.objects.filter(status=RegistryStatus.REVOKED).count() == len(inside)
    outside.registry.refresh_from_db()
    assert outside.registry.status == RegistryStatus.UNCLAIMED


def test_return_query_cannot_redirect_off_site(admin_client):
    student = make_student()
    response = bulk(admin_client, "revoke", [student], return_query="//evil.example/x")
    assert response["Location"].startswith(reverse("accounts:registry_list"))
    assert "evil.example" not in response["Location"].split("?")[0]


# --- HOD and roles through the screens -------------------------------------------------


def test_admin_assigns_and_removes_a_hod(admin_client):
    department = DepartmentFactory()
    teacher = make_teacher(department)
    url = reverse("accounts:registry_hod", args=[teacher.registry.pk])
    admin_client.post(url, {"action": "assign", "department": department.pk})
    teacher.refresh_from_db()
    assert teacher.is_hod and teacher.hod_department == department
    page = admin_client.get(reverse("accounts:registry_edit", args=[teacher.registry.pk]))
    assert "heads" in page.content.decode()
    admin_client.post(url, {"action": "remove"})
    teacher.refresh_from_db()
    assert not teacher.is_hod


def test_hod_screen_ignores_student_entries(admin_client, secret_student):
    url = reverse("accounts:registry_hod", args=[secret_student.registry.pk])
    assert admin_client.post(url, {"action": "assign", "department": 1}).status_code == 404


def test_admin_changes_a_role_through_the_screen(admin_client):
    teacher = claim(make_teacher())
    url = reverse("accounts:user_role", args=[teacher.pk])
    admin_client.post(url, {"role": "admin"})
    assert User.objects.get(pk=teacher.pk).role == Role.ADMIN
    student = claim(make_student())
    admin_client.post(reverse("accounts:user_role", args=[student.pk]), {"role": "admin"})
    assert User.objects.get(pk=student.pk).role == Role.STUDENT


def test_user_screens_never_show_ids(admin_client, secret_student):
    account = claim(secret_student)
    for url in (reverse("accounts:user_list"), reverse("accounts:user_detail", args=[account.pk])):
        body = admin_client.get(url).content.decode()
        assert account.username in body
        assert SECRET_ID not in body and SECRET_NAME not in body


def test_user_list_filters(admin_client):
    student = claim(make_student(), nickname="Rafi")
    teacher = claim(make_teacher())
    url = reverse("accounts:user_list")
    body = admin_client.get(url, {"role": "student"}).content.decode()
    assert student.username in body and teacher.username not in body
    assert student.username in admin_client.get(url, {"q": "rafi"}).content.decode()


def test_screens_are_translated_to_bangla(admin_client, secret_student):
    admin_client.defaults["HTTP_ACCEPT_LANGUAGE"] = "bn"
    page = admin_client.get(reverse("accounts:registry_list")).content.decode()
    assert "আইডি রেজিস্ট্রি" in page and "ID registry" not in page
    duplicate = admin_client.post(
        reverse("accounts:registry_create", args=["student"]),
        student_form(secret_student.registry.department, external_id=SECRET_ID),
    )
    assert "এই আইডি আগেই নিবন্ধিত।" in duplicate.content.decode()

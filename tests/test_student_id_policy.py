import pytest
from django.contrib.auth.models import AnonymousUser
from django.db import connection
from django.template import Context, Template
from django.test.utils import CaptureQueriesContext

from apps.accounts.models import StudentProfile
from apps.accounts.services.student_id_policy import (
    MASK,
    can_view_student_id,
    with_visible_ids,
)
from tests.factories import (
    DepartmentFactory,
    claim,
    make_admin,
    make_hod,
    make_student,
    make_teacher,
)

pytestmark = pytest.mark.django_db

SECRET_ID = "2101777"
SECRET_NAME = "Nusrat Jahan"


@pytest.fixture
def own_department():
    return DepartmentFactory()


@pytest.fixture
def student(own_department):
    return make_student(own_department, external_id=SECRET_ID, full_name=SECRET_NAME)


def render(profile, viewer, tag="student_id"):
    template = Template("{% load identity %}{{ profile|" + tag + ":viewer }}")
    return template.render(Context({"profile": profile, "viewer": viewer}))


@pytest.fixture
def viewers(own_department):
    other_student = claim(make_student(own_department))
    return {
        "anonymous": AnonymousUser(),
        "student": other_student,
        "student_same_department": claim(make_student(own_department)),
        "teacher_same_department": claim(make_teacher(own_department)),
        "hod_same_department": make_hod(own_department),
        "hod_other_department": make_hod(),
        "admin": make_admin(),
    }


ALLOWED = {"hod_same_department", "admin"}


@pytest.mark.parametrize(
    "who",
    [
        "anonymous",
        "student",
        "student_same_department",
        "teacher_same_department",
        "hod_same_department",
        "hod_other_department",
        "admin",
    ],
)
def test_policy_matrix(who, viewers, student):
    assert can_view_student_id(viewers[who], student) is (who in ALLOWED)


def test_students_never_see_their_own_id_through_the_policy(own_department):
    profile = make_student(own_department)
    owner = claim(profile)
    assert can_view_student_id(owner, profile) is False


def test_inactive_admin_and_inactive_hod_see_nothing(student, own_department):
    admin = make_admin()
    admin.is_active = False
    hod = make_hod(own_department)
    hod.is_active = False
    assert not can_view_student_id(admin, student)
    assert not can_view_student_id(hod, student)


def test_a_hod_who_was_removed_loses_access(own_department, student):
    hod = make_hod(own_department)
    assert can_view_student_id(hod, student)
    profile = hod.teacher_profile
    profile.is_hod, profile.hod_department = False, None
    profile.save()
    hod.refresh_from_db()
    assert not can_view_student_id(hod, student)


@pytest.mark.parametrize("who", ["student", "teacher_same_department", "hod_other_department"])
def test_filters_mask_for_viewers_without_access(who, viewers, student):
    assert render(student, viewers[who]) == MASK
    assert render(student, viewers[who], "student_name") == MASK


@pytest.mark.parametrize("who", ["hod_same_department", "admin"])
def test_filters_reveal_for_viewers_with_access(who, viewers, student):
    assert render(student, viewers[who]) == SECRET_ID
    assert render(student, viewers[who], "student_name") == SECRET_NAME


def test_filter_shows_empty_name_when_none_is_on_file(own_department):
    nameless = make_student(own_department, full_name="")
    assert render(nameless, make_admin(), "student_name") == ""


@pytest.mark.parametrize("who", ["student", "teacher_same_department", "hod_other_department"])
def test_visible_ids_queryset_never_returns_hidden_values(who, viewers, student):
    rows = list(with_visible_ids(StudentProfile.objects.all(), viewers[who]))
    assert rows
    for row in rows:
        assert row.ids_visible is False
        assert row.visible_student_id is None
        assert row.visible_full_name is None
        assert render(row, viewers[who]) == MASK
        assert SECRET_ID not in repr(row.__dict__) and SECRET_NAME not in repr(row.__dict__)
        assert SECRET_ID not in repr(row.registry.__dict__)


def test_visible_ids_queryset_reveals_only_own_department_to_a_hod(own_department, student):
    foreign = make_student(external_id="2199888", full_name="Other Dept")
    hod = make_hod(own_department)
    by_pk = {row.pk: row for row in with_visible_ids(StudentProfile.objects.all(), hod)}
    assert by_pk[student.pk].visible_student_id == SECRET_ID
    assert by_pk[student.pk].visible_full_name == SECRET_NAME
    assert by_pk[foreign.pk].visible_student_id is None
    assert render(by_pk[foreign.pk], hod) == MASK
    assert render(by_pk[student.pk], hod) == SECRET_ID


def test_visible_ids_queryset_shows_everything_to_an_admin(student):
    foreign = make_student(external_id="2199888")
    rows = {row.pk: row for row in with_visible_ids(StudentProfile.objects.all(), make_admin())}
    assert rows[student.pk].visible_student_id == SECRET_ID
    assert rows[foreign.pk].visible_student_id == "2199888"


def test_visible_ids_queryset_does_not_query_per_row(own_department):
    hod = make_hod(own_department)
    for _ in range(6):
        make_student(own_department)
    assert hod.is_hod  # warm the viewer's own profile cache; only the list is measured
    with CaptureQueriesContext(connection) as queries:
        rows = list(with_visible_ids(StudentProfile.objects.all(), hod))
        for row in rows:
            render(row, hod)
    assert len(rows) == 6
    assert len(queries) == 1


def test_raw_values_are_deferred_from_the_registry_join(student):
    row = with_visible_ids(StudentProfile.objects.filter(pk=student.pk), make_teacher_user()).get()
    assert "external_id" in row.registry.get_deferred_fields()
    assert "full_name" in row.registry.get_deferred_fields()


def make_teacher_user():
    return claim(make_teacher())

from io import StringIO

import pytest
from django.core.management import CommandError, call_command
from django.db import DatabaseError, connection, transaction
from django.utils import translation

from apps.auditlog.models import GENESIS_HASH, AuditEvent, AuditLogImmutableError
from apps.auditlog.services import audit
from apps.core.permissions import Role
from tests.factories import make_user


@pytest.fixture
def actor():
    return make_user("tch_q8w2", Role.TEACHER)


@pytest.fixture
def events(rf, actor):
    request = rf.get("/", HTTP_USER_AGENT="pytest-agent", REMOTE_ADDR="203.0.113.7")
    request.user = actor
    request.request_id = "req-0000aaaa"
    return [
        audit.record("auth.login", request=request),
        audit.record("academics.course_created", actor=actor, target=actor, department_id=3),
        audit.record("system.backup_done", metadata={"files": 3, "tables": ["a", "b"]}),
    ]


def raw_update(sql, params):
    with connection.cursor() as cursor:
        cursor.execute(sql, params)


@pytest.mark.django_db
def test_record_captures_context(events, actor):
    login = events[0]
    assert login.actor_id == actor.pk
    assert login.actor_username == "tch_q8w2"
    assert login.ip == "203.0.113.7"
    assert login.user_agent == "pytest-agent"
    assert login.request_id == "req-0000aaaa"
    assert events[1].object_type == "accounts.user"
    assert events[1].object_id == str(actor.pk)
    assert events[1].department_id == 3


@pytest.mark.django_db
def test_chain_links_rows(events):
    assert events[0].prev_hash == GENESIS_HASH
    assert events[1].prev_hash == events[0].hash
    assert events[2].prev_hash == events[1].hash
    report = audit.verify_chain()
    assert report.ok
    assert report.checked == 3


@pytest.mark.django_db
def test_rows_cannot_be_updated_or_deleted_through_the_orm(events):
    event = AuditEvent.objects.get(pk=events[0].pk)
    event.action = "auth.logout"
    with pytest.raises(AuditLogImmutableError):
        event.save()
    with pytest.raises(AuditLogImmutableError):
        event.delete()
    with pytest.raises(AuditLogImmutableError):
        AuditEvent.objects.filter(pk=event.pk).update(action="auth.logout")
    with pytest.raises(AuditLogImmutableError):
        AuditEvent.objects.all().delete()
    with pytest.raises(AuditLogImmutableError):
        AuditEvent.objects.bulk_create([AuditEvent(action="x.y")])
    with pytest.raises(AuditLogImmutableError):
        AuditEvent.objects.create(action="x.y", prev_hash="f" * 64, hash="e" * 64)
    assert audit.verify_chain().ok


@pytest.mark.django_db
@pytest.mark.skipif(connection.vendor == "postgresql", reason="PostgreSQL refuses raw tampering")
def test_verify_detects_tampered_content(events):
    raw_update(
        "UPDATE auditlog_auditevent SET action = %s WHERE id = %s", ["auth.logout", events[1].pk]
    )
    report = audit.verify_chain()
    assert (report.broken_at, report.fault, report.checked) == (events[1].pk, "content", 1)
    with translation.override("en"), pytest.raises(CommandError, match=f"event {events[1].pk}"):
        call_command("verify_audit_chain", stdout=StringIO())


@pytest.mark.django_db
@pytest.mark.skipif(connection.vendor == "postgresql", reason="PostgreSQL refuses raw tampering")
def test_verify_detects_deleted_row(events):
    raw_update("DELETE FROM auditlog_auditevent WHERE id = %s", [events[1].pk])
    report = audit.verify_chain()
    assert (report.broken_at, report.fault) == (events[2].pk, "link")


@pytest.mark.django_db
@pytest.mark.skipif(
    connection.vendor != "postgresql", reason="database-level guard is PostgreSQL only"
)
def test_database_refuses_update_and_delete(events):
    for sql in ("UPDATE auditlog_auditevent SET action = 'x.y'", "DELETE FROM auditlog_auditevent"):
        with pytest.raises(DatabaseError), transaction.atomic():
            raw_update(sql, [])
    assert audit.verify_chain().ok


@pytest.mark.django_db
def test_verify_command_reports_success(events):
    out = StringIO()
    call_command("verify_audit_chain", stdout=out)
    assert "3" in out.getvalue()


@pytest.mark.parametrize(
    "metadata",
    [
        {"password": "x"},
        {"new_password": "x"},
        {"otp": "123456"},
        {"activation_code": "ABCD"},
        {"code": "ABCD"},
        {"nested": {"totp_secret": "x"}},
        {"comment": "nice"},
        {"answers": [1, 2]},
        {"feedback_text": "x"},
        {"note": "x" * 201},
        {"when": object()},
    ],
)
@pytest.mark.django_db
def test_secrets_and_free_text_are_refused(metadata):
    with pytest.raises(ValueError):
        audit.record("test.refused", metadata=metadata)
    assert not AuditEvent.objects.exists()


@pytest.mark.django_db
def test_metadata_strings_are_scrubbed():
    event = audit.record("test.scrubbed", metadata={"course_code": "CSE-101", "to": "a@b.edu"})
    assert event.metadata == {"course_code": "CSE-101", "to": "[REDACTED]"}


@pytest.mark.parametrize("action", ["login", "Auth.Login", "auth.", "auth login", ""])
@pytest.mark.django_db
def test_action_names_are_validated(action):
    with pytest.raises(ValueError):
        audit.record(action)


@pytest.mark.django_db
def test_ipv4_mapped_address_round_trips_through_hash(rf):
    request = rf.get("/", REMOTE_ADDR="::ffff:192.0.2.1")
    request.user = type("Anon", (), {"is_authenticated": False})()
    audit.record("auth.login_failed", request=request)
    assert audit.verify_chain().ok

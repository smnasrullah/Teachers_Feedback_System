import json
import logging
import sys

import pytest

from apps.core.logging import (
    REDACTED,
    JsonFormatter,
    RequestIdFilter,
    ScrubFilter,
    request_id_var,
    scrub_text,
)


def make_record(msg, *args, exc_info=None):
    return logging.LogRecord("tfs.test", logging.INFO, __file__, 1, msg, args, exc_info)


def scrubbed(msg, *args):
    record = make_record(msg, *args)
    ScrubFilter().filter(record)
    return record.getMessage()


@pytest.mark.parametrize(
    ("text", "secret"),
    [
        ("login password=hunter2isweak", "hunter2isweak"),
        ("POST {'username': 'stu_k7', 'password': 'my secret pass'}", "my secret pass"),
        ("new_password: Tr0ub4dor", "Tr0ub4dor"),
        ("GET /signup/verify?otp=482913&next=/", "482913"),
        ("your code is 482913", "482913"),
        ("OTP in Bangla digits ৪৮২৯১৩ sent", "৪৮২৯১৩"),
        ("GET /activate?code=K7X9-A2B4-C3D5", "K7X9-A2B4-C3D5"),
        ("activation_code=XY7Q", "XY7Q"),
        ("issued K7X9-A2B4-C3D5 to registry 4", "K7X9-A2B4-C3D5"),
        ("csrfmiddlewaretoken=abcdEFGH", "abcdEFGH"),
        ("Authorization: Bearer abc.def.ghi", "abc.def.ghi"),
        ("totp_secret=JBSWY3DPEHPK3PXP", "JBSWY3DPEHPK3PXP"),
        (
            "reset link /reset/MQ/c3k2ab-9f8e7d6c5b4a39281706f5e4d3c2b1a0/",
            "9f8e7d6c5b4a39281706f5e4d3c2b1a0",
        ),
        ("stored gAAAAABlZ2V0dGluZy1zZWNyZXQ=", "gAAAAABlZ2V0dGluZy1zZWNyZXQ="),
        ("contact rahim@example.edu now", "rahim@example.edu"),
        ("call +8801712345678 please", "01712345678"),
    ],
)
def test_scrubber_redacts_secrets_and_pii(text, secret):
    result = scrub_text(text)
    assert secret not in result
    assert REDACTED in result


@pytest.mark.parametrize(
    "text",
    [
        "GET /dashboard/ HTTP/1.1 200 5123",
        "status_code=404 for course_code CSE-101",
        "Invalid password for account",
        "apps.core.middleware loaded in 12 ms",
    ],
)
def test_scrubber_keeps_ordinary_text(text):
    assert scrub_text(text) == text


def test_long_free_text_arguments_are_dropped():
    comment = "শিক্ষক খুব ভালো পড়ান, তবে ক্লাসে আরও উদাহরণ দিলে ভালো হতো। " * 4
    message = scrubbed("validation failed for %s", comment)
    assert comment not in message
    assert "free text" in message


def test_mapping_args_are_scrubbed():
    record = make_record("%(field)s", {"field": "x" * 500})
    record.args = {"field": "x" * 500}
    ScrubFilter().filter(record)
    assert "x" * 500 not in record.getMessage()


def test_exception_text_is_scrubbed():
    try:
        raise ValueError("bad token=abcdef123456ghijkl")
    except ValueError:
        record = make_record("failed", exc_info=sys.exc_info())
    ScrubFilter().filter(record)
    assert "abcdef123456ghijkl" not in record.exc_text
    assert "ValueError" in record.exc_text


def test_json_formatter_emits_one_object_with_request_id():
    token = request_id_var.set("req-123456")
    try:
        record = make_record("user password=hunter2 signed in")
        RequestIdFilter().filter(record)
        ScrubFilter().filter(record)
    finally:
        request_id_var.reset(token)
    payload = json.loads(JsonFormatter().format(record))
    assert payload["request_id"] == "req-123456"
    assert payload["level"] == "INFO"
    assert "hunter2" not in payload["message"]


@pytest.mark.parametrize("logger_name", ["", "django", "django.server"])
def test_configured_handlers_scrub(logger_name):
    handlers = [
        h for h in logging.getLogger(logger_name).handlers if type(h) is logging.StreamHandler
    ]
    assert handlers
    for handler in handlers:
        assert {type(f) for f in handler.filters} >= {ScrubFilter, RequestIdFilter}

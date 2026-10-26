"""Log scrubbing, request-id tagging and JSON output.

``ScrubFilter`` runs on every handler, so nothing reaches stdout or a log shipper
without passing through it (CLAUDE.md rule 7, BLUEPRINT §5.4 "Secret/PII in logs").
"""

import json
import logging
import re
from collections.abc import Mapping
from contextvars import ContextVar
from datetime import UTC, datetime

request_id_var: ContextVar[str] = ContextVar("request_id", default="-")

REDACTED = "[REDACTED]"
FREE_TEXT_LIMIT = 120
MESSAGE_LIMIT = 2000

_SENSITIVE_NAME = (
    r"(?<![A-Za-z0-9_])(?:"
    r"[A-Za-z_]*(?:password|passwd|passphrase|secret|token|otp|totp|api_?key|authorization"
    r"|cookie|sessionid|session_key)[A-Za-z_]*"
    r"|(?:activation|recovery|verification|reset|auth|backup)?[_-]?code"
    r")"
)

_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    # before key=value, which would otherwise redact only the scheme word
    (re.compile(r"(?i)\b(bearer|basic)\s+[A-Za-z0-9._~+/=-]+"), rf"\1 {REDACTED}"),
    # key=value, key: value, 'key': 'value' (query strings, form dumps, dict reprs)
    (
        re.compile(
            rf"(?i)(?P<key>{_SENSITIVE_NAME})(?P<sep>[\"']?\s*[:=]\s*)"
            r"(?P<value>\"[^\"]*\"|'[^']*'|[^\s\"'&,;}\]]+)"
        ),
        rf"\g<key>\g<sep>{REDACTED}",
    ),
    (re.compile(r"\bgAAAAA[A-Za-z0-9_=-]+"), REDACTED),  # Fernet token
    (re.compile(r"\beyJ[\w-]+\.[\w-]+\.[\w-]*"), REDACTED),  # JWT
    (re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+"), REDACTED),  # e-mail
    (re.compile(r"(?<!\d)(?:\+?88)?01[3-9]\d{8}(?!\d)"), REDACTED),  # BD mobile
    (re.compile(r"\b[A-Z0-9]{4}(?:-[A-Z0-9]{4}){2,}\b"), REDACTED),  # grouped one-time code
    # long random-looking strings (session keys, reset tokens, API keys)
    (
        re.compile(
            r"(?<![\w-])(?=[\w-]*\d)(?=[\w-]*[A-Za-z])[A-Za-z0-9_-]{24,}(?![\w-])", re.ASCII
        ),
        REDACTED,
    ),
    (re.compile(r"(?<!\d)\d{6}(?!\d)"), REDACTED),  # OTP (any script's digits)
)


def scrub_text(text: str) -> str:
    for pattern, replacement in _PATTERNS:
        text = pattern.sub(replacement, text)
    return text


def _scrub_arg(value):
    if isinstance(value, str) and len(value) > FREE_TEXT_LIMIT:
        return f"[REDACTED free text, {len(value)} chars]"
    return value


class ScrubFilter(logging.Filter):
    """Redact secrets/PII and drop long free text (comments, feedback) from records."""

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.args, Mapping):
            record.args = {key: _scrub_arg(value) for key, value in record.args.items()}
        elif record.args:
            record.args = tuple(_scrub_arg(value) for value in record.args)
        try:
            message = record.getMessage()
        except (TypeError, ValueError):
            message = str(record.msg)
        message = scrub_text(message)
        if len(message) > MESSAGE_LIMIT:
            message = f"{message[:MESSAGE_LIMIT]}… [truncated]"
        record.msg, record.args = message, None
        if record.exc_info and not record.exc_text:
            record.exc_text = logging.Formatter().formatException(record.exc_info)
        if record.exc_text:
            record.exc_text = scrub_text(record.exc_text)
        return True


class RequestIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_var.get()
        return True


class JsonFormatter(logging.Formatter):
    """One JSON object per line with a fixed set of keys (no arbitrary ``extra`` data)."""

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "time": datetime.fromtimestamp(record.created, UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": getattr(record, "request_id", "-"),
        }
        status_code = getattr(record, "status_code", None)
        if isinstance(status_code, int):
            payload["status_code"] = status_code
        if record.exc_info and not record.exc_text:
            record.exc_text = self.formatException(record.exc_info)
        if record.exc_text:
            payload["exception"] = record.exc_text
        return json.dumps(payload, ensure_ascii=False)


def build_logging_config(*, json_logs: bool, level: str) -> dict:
    handler = {
        "class": "logging.StreamHandler",
        "formatter": "json" if json_logs else "text",
        "filters": ["request_id", "scrub"],
    }
    return {
        "version": 1,
        "disable_existing_loggers": False,
        "filters": {
            "request_id": {"()": "apps.core.logging.RequestIdFilter"},
            "scrub": {"()": "apps.core.logging.ScrubFilter"},
        },
        "formatters": {
            "text": {"format": "%(asctime)s %(levelname)s [%(request_id)s] %(name)s: %(message)s"},
            "json": {"()": "apps.core.logging.JsonFormatter"},
        },
        "handlers": {"console": handler},
        "root": {"handlers": ["console"], "level": level},
        "loggers": {
            # Replace Django's default handlers so request lines and errors are scrubbed too.
            "django": {"handlers": ["console"], "level": level, "propagate": False},
            "django.server": {"handlers": ["console"], "level": level, "propagate": False},
        },
    }

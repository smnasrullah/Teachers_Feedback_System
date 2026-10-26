"""Account claiming: ID + activation code, contact verification, then the account itself.

Every failure of the first step looks the same to the caller (``find_claimable`` returns
``None``) and costs the same work, whether the ID is unknown, claimed, revoked or the code
is wrong, expired or used.
"""

import hmac

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.db import IntegrityError, transaction
from django.utils import timezone, translation
from django.utils.translation import gettext as _

from apps.accounts.models import (
    EMAIL_INDEX_PURPOSE,
    PHONE_INDEX_PURPOSE,
    IdRegistry,
    IdType,
    OneTimeCode,
    OtpPurpose,
    RegistryStatus,
    User,
    registry_index,
)
from apps.accounts.services import activation, otp
from apps.accounts.services.identifiers import (
    clean_registry_id,
    normalize_activation_code,
    normalize_phone,
)
from apps.auditlog.services import audit
from apps.core.encryption import blind_index
from apps.core.permissions import Role
from apps.notifications.otp import EMAIL, SMS

MIN_PHONE_DIGITS = 8
MAX_PHONE_DIGITS = 15
# What a code is compared with when no registry row matched, so a miss costs the same.
_MISS = "0" * 64


class SignupError(Exception):
    """The sign-up cannot continue; the person starts again from the first step."""


def find_claimable(external_id: str, code: str) -> IdRegistry | None:
    """The unclaimed, unrevoked registry row this ID and unexpired unused code belong to."""
    try:
        normalized_id = clean_registry_id(external_id)
    except ValidationError:
        normalized_id = ""
    submitted = activation.hash_code(code) if normalize_activation_code(code) else _MISS
    rows = list(IdRegistry.objects.filter(external_id_index=registry_index(normalized_id) or ""))
    now = timezone.now()
    match = None
    for row in rows or [None]:
        stored = (row.activation_code_hash if row else "") or _MISS
        same_code = hmac.compare_digest(stored, submitted)
        usable = (
            row is not None
            and row.status == RegistryStatus.UNCLAIMED
            and row.activation_used_at is None
            and row.activation_expires_at is not None
            and row.activation_expires_at > now
        )
        if same_code and usable:
            match = row
    return match


def parse_contact(raw: str) -> otp.Contact:
    """An e-mail address or (when SMS is on) a phone number, in canonical form."""
    raw = raw.strip()
    if "@" in raw:
        try:
            validate_email(raw)
        except ValidationError:
            raise ValidationError(_("Enter a valid e-mail address."), code="invalid") from None
        return otp.Contact(EMAIL, raw.lower())
    phone = normalize_phone(raw)
    if not otp.sms_enabled() or not MIN_PHONE_DIGITS <= len(phone) - 1 <= MAX_PHONE_DIGITS:
        raise ValidationError(_("Enter a valid e-mail address."), code="invalid")
    return otp.Contact(SMS, phone)


def contact_in_use(contact: otp.Contact) -> bool:
    if contact.channel == EMAIL:
        return User.objects.filter(
            contact_email_index=blind_index(contact.destination, EMAIL_INDEX_PURPOSE)
        ).exists()
    return User.objects.filter(
        contact_phone_index=blind_index(contact.destination, PHONE_INDEX_PURPOSE)
    ).exists()


def start_verification(registry: IdRegistry, contact: otp.Contact) -> OneTimeCode:
    if contact_in_use(contact):
        raise ValidationError(
            _("This e-mail address or phone number cannot be used. Try another."),
            code="contact_in_use",
        )
    return otp.start(
        OtpPurpose.SIGNUP,
        channel=contact.channel,
        destination=contact.destination,
        registry=registry,
        keep_destination=True,
    )


def _usable_language() -> str:
    language = translation.get_language() or settings.LANGUAGE_CODE
    return language if language in dict(settings.LANGUAGES) else settings.LANGUAGE_CODE


@transaction.atomic
def create_account(registry_pk: int, challenge_id, password: str, *, request=None) -> User:
    """Create the account, claim the registry row and burn the activation code, atomically."""
    registry = (
        IdRegistry.objects.select_for_update(of=("self",))
        .select_related("department")
        .get(pk=registry_pk)
    )
    challenge = otp.get_active(challenge_id, OtpPurpose.SIGNUP)
    if (
        challenge is None
        or challenge.registry_id != registry.pk
        or not challenge.destination
        or not otp.is_verified(challenge)
    ):
        raise SignupError
    now = timezone.now()
    if (
        registry.status != RegistryStatus.UNCLAIMED
        or registry.activation_used_at is not None
        or not registry.activation_code_hash
        or registry.activation_expires_at is None
        or registry.activation_expires_at <= now
    ):
        raise SignupError
    role = Role.STUDENT if registry.id_type == IdType.STUDENT else Role.TEACHER
    contact_field = "contact_email" if challenge.channel == EMAIL else "contact_phone"
    try:
        with transaction.atomic():
            user = User.objects.create_user(
                role,
                password,
                department=registry.department,
                language=_usable_language(),
                **{contact_field: challenge.destination},
            )
    except IntegrityError:
        raise SignupError from None
    registry.claimed_by = user
    registry.status = RegistryStatus.CLAIMED
    registry.activation_code_hash = ""
    registry.activation_expires_at = None
    registry.activation_used_at = now
    registry.save(
        update_fields=[
            "claimed_by",
            "status",
            "activation_code_hash",
            "activation_expires_at",
            "activation_used_at",
        ]
    )
    otp.consume(challenge)
    audit.record(
        "auth.signup",
        request=request,
        actor=user,
        target=user,
        department_id=user.department_id,
        metadata={"id_type": registry.id_type, "channel": challenge.channel},
    )
    return user

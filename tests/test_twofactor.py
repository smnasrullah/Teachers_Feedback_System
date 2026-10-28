import pyotp
import pytest

from apps.accounts.models import RecoveryCode
from apps.accounts.services import twofactor
from apps.accounts.templatetags.identity import mask_contact
from tests.auth_helpers import code_for_secret, enable_totp, totp_code
from tests.factories import claim, make_admin, make_student

pytestmark = pytest.mark.django_db


def pending_user():
    user = claim(make_student())
    twofactor.begin_enrolment(user)
    return user


def test_enrolment_keeps_one_secret_until_confirmed():
    user = pending_user()
    secret = user.totp_secret
    assert twofactor.begin_enrolment(user) == secret
    assert not user.totp_enabled
    assert pyotp.TOTP(secret).provisioning_uri(name=user.username).startswith("otpauth://totp/")
    uri = twofactor.provisioning_uri(secret, user.username)
    assert "issuer=Teacher%20Feedback%20System" in uri
    assert user.username in uri


def test_secret_is_encrypted_at_rest():
    from django.db import connection

    user = pending_user()
    with connection.cursor() as cursor:
        cursor.execute("SELECT totp_secret FROM accounts_user WHERE id = %s", [user.pk])
        stored = cursor.fetchone()[0]
    assert user.totp_secret not in stored


def test_confirmation_needs_a_valid_code_and_returns_eight_codes():
    user = pending_user()
    assert twofactor.confirm_enrolment(user, "000000") is None
    assert not user.totp_enabled
    codes = twofactor.confirm_enrolment(user, totp_code(user))
    assert len(codes) == 8
    assert len(set(codes)) == 8
    assert user.totp_enabled


def test_neighbouring_time_steps_are_accepted_but_far_ones_are_not():
    user = pending_user()
    assert twofactor.verify_totp(user, totp_code(user, steps_ahead=1))
    other = pending_user()
    assert not twofactor.verify_totp(other, totp_code(other, steps_ahead=3))


def test_a_code_cannot_be_replayed_nor_an_older_one_used_after_a_newer():
    user = pending_user()
    newer = totp_code(user, steps_ahead=1)
    older = totp_code(user)
    assert twofactor.verify_totp(user, newer)
    assert not twofactor.verify_totp(user, newer)
    assert not twofactor.verify_totp(user, older)


def test_codes_with_separators_and_bangla_digits_are_normalised():
    user = pending_user()
    code = totp_code(user)
    bangla = code.translate(str.maketrans("0123456789", "০১২৩৪৫৬৭৮৯"))
    assert twofactor.verify_totp(user, f"{bangla[:3]} {bangla[3:]}")


def test_recovery_codes_are_single_use_and_hashed():
    user = claim(make_student())
    twofactor.begin_enrolment(user)
    codes = twofactor.confirm_enrolment(user, totp_code(user))
    stored = list(RecoveryCode.objects.filter(user=user).values_list("code_hash", flat=True))
    assert len(stored) == 8
    assert all(code.replace("-", "") not in " ".join(stored) for code in codes)
    result = twofactor.check_second_factor(user, codes[0].lower())
    assert result.ok and result.recovery and result.recovery_left == 7
    assert not twofactor.check_second_factor(user, codes[0]).ok
    assert twofactor.recovery_codes_left(user) == 7


def test_wrong_or_malformed_recovery_codes_fail():
    user = make_admin()
    enable_totp(user)
    for attempt in ("", "ABCDE-FGHIJ", "short", "x" * 40):
        assert not twofactor.check_second_factor(user, attempt).ok


def test_regenerating_invalidates_the_old_codes():
    user = claim(make_student())
    twofactor.begin_enrolment(user)
    old = twofactor.confirm_enrolment(user, totp_code(user))
    new = twofactor.regenerate_recovery_codes(user)
    assert not twofactor.check_second_factor(user, old[0]).ok
    assert twofactor.check_second_factor(user, new[0]).ok


def test_clear_forgets_the_secret_and_codes():
    user = claim(make_student())
    enable_totp(user)
    twofactor.clear(user)
    user.refresh_from_db()
    assert not user.totp_enabled
    assert user.totp_secret is None
    assert not user.recovery_codes.exists()


def test_qr_is_an_inline_svg_image():
    user = pending_user()
    assert twofactor.qr_data_uri(user.totp_secret, user.username).startswith("data:image/svg+xml")


def test_manual_key_is_the_secret_in_groups_of_four():
    key = twofactor.manual_key("ABCDEFGHIJKLMNOP")
    assert key == "ABCD EFGH IJKL MNOP"


@pytest.mark.parametrize("code", ["", "12345", "1234567", "abcdef", "০১২"])
def test_malformed_codes_never_match(code):
    assert twofactor.matching_step(twofactor.new_secret(), code) is None


def test_matching_step_skips_steps_already_used():
    secret = twofactor.new_secret()
    step = twofactor.matching_step(secret, code_for_secret(secret))
    assert step is not None
    assert twofactor.matching_step(secret, code_for_secret(secret), after=step) is None


def test_an_unknown_account_never_passes_the_second_factor():
    assert not twofactor.check_second_factor(None, "123456").ok
    pending = pending_user()  # a secret, but not enabled yet
    assert not twofactor.check_second_factor(pending, totp_code(pending)).ok


def test_replacing_the_secret_needs_a_code_from_the_new_one():
    user = claim(make_student())
    codes = enable_totp(user)
    new = twofactor.new_secret()
    assert not twofactor.replace_secret(user, new, totp_code(user, steps_ahead=1))
    assert twofactor.replace_secret(user, new, code_for_secret(new))
    user.refresh_from_db()
    assert user.totp_secret == new
    assert twofactor.check_second_factor(user, codes[0]).ok  # recovery codes survive


def test_mask_contact_hides_most_of_the_address():
    assert mask_contact("ana.rahman@example.com") == "an***@example.com"
    assert mask_contact("+8801712345678") == "+880*******678"
    assert mask_contact(None) == "***"

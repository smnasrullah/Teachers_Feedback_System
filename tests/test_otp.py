from datetime import timedelta

import pytest
from django.utils import timezone

from apps.accounts.models import OneTimeCode, OtpPurpose
from apps.accounts.services import otp
from apps.accounts.services.otp import ResendError, VerifyStatus
from tests.factories import claim, make_student

pytestmark = pytest.mark.django_db

PURPOSE = OtpPurpose.PASSWORD_RESET


def start(sent, destination="ana@example.com"):
    challenge = otp.start(PURPOSE, channel="email", destination=destination)
    return challenge, sent[-1].code


def test_code_is_six_digits_delivered_and_stored_only_hashed(sent):
    challenge, code = start(sent)
    assert len(code) == 6
    assert code.isdigit()
    assert sent[-1].destination == "ana@example.com"
    stored = OneTimeCode.objects.get(pk=challenge.pk)
    assert code not in stored.code_hash
    assert len(stored.code_hash) == 64
    assert stored.destination is None  # only sign-up keeps the contact it is verifying


def test_correct_code_verifies_and_is_remembered(sent):
    challenge, code = start(sent)
    status, checked = otp.verify(challenge.pk, PURPOSE, code)
    assert status is VerifyStatus.OK
    assert otp.is_verified(checked)


def test_wrong_code_is_rejected_and_counted(sent):
    challenge, code = start(sent)
    wrong = "000000" if code != "000000" else "111111"
    status, checked = otp.verify(challenge.pk, PURPOSE, wrong)
    assert status is VerifyStatus.WRONG
    assert checked.attempts == 1
    assert not otp.is_verified(checked)


def test_bangla_digits_and_spaces_are_accepted(sent):
    challenge, code = start(sent)
    bangla = " ".join(code.translate(str.maketrans("0123456789", "০১২৩৪৫৬৭৮৯")))
    assert otp.verify(challenge.pk, PURPOSE, bangla)[0] is VerifyStatus.OK


def test_code_expires_after_five_minutes(sent):
    challenge, code = start(sent)
    OneTimeCode.objects.filter(pk=challenge.pk).update(
        expires_at=timezone.now() - timedelta(seconds=1)
    )
    assert otp.verify(challenge.pk, PURPOSE, code)[0] is VerifyStatus.EXPIRED


def test_default_lifetime_is_five_minutes(sent, settings):
    challenge, _ = start(sent)
    lifetime = challenge.expires_at - challenge.sent_at
    assert lifetime == timedelta(minutes=5)
    assert settings.OTP_MAX_ATTEMPTS == 5


def test_five_wrong_attempts_lock_the_code_even_for_the_right_one(sent):
    challenge, code = start(sent)
    wrong = "000000" if code != "000000" else "111111"
    for _attempt in range(5):
        assert otp.verify(challenge.pk, PURPOSE, wrong)[0] is VerifyStatus.WRONG
    assert otp.verify(challenge.pk, PURPOSE, code)[0] is VerifyStatus.LOCKED


def test_code_for_another_purpose_or_unknown_challenge_never_verifies(sent):
    challenge, code = start(sent)
    assert otp.verify(challenge.pk, OtpPurpose.SIGNUP, code)[0] is VerifyStatus.EXPIRED
    assert otp.verify("not-a-uuid", PURPOSE, code)[0] is VerifyStatus.EXPIRED


def test_resend_has_a_cooldown(sent):
    challenge, _ = start(sent)
    with pytest.raises(ResendError) as refused:
        otp.resend(challenge, "ana@example.com")
    assert 0 < refused.value.wait <= 60
    assert len(sent) == 1


def test_resend_after_cooldown_replaces_the_code_and_resets_attempts(sent):
    challenge, old = start(sent)
    wrong = "000000" if old != "000000" else "111111"
    otp.verify(challenge.pk, PURPOSE, wrong)
    OneTimeCode.objects.filter(pk=challenge.pk).update(
        sent_at=timezone.now() - timedelta(seconds=61)
    )
    otp.resend(challenge, "ana@example.com")
    new = sent[-1].code
    refreshed = OneTimeCode.objects.get(pk=challenge.pk)
    assert refreshed.attempts == 0
    assert refreshed.send_count == 2
    if new != old:
        assert otp.verify(challenge.pk, PURPOSE, old)[0] is VerifyStatus.WRONG
    assert otp.verify(challenge.pk, PURPOSE, new)[0] is VerifyStatus.OK


def test_resends_are_capped(sent, settings):
    challenge, _ = start(sent)
    for _send in range(settings.OTP_MAX_SENDS - 1):
        OneTimeCode.objects.filter(pk=challenge.pk).update(
            sent_at=timezone.now() - timedelta(seconds=61)
        )
        otp.resend(challenge, "ana@example.com")
    OneTimeCode.objects.filter(pk=challenge.pk).update(
        sent_at=timezone.now() - timedelta(seconds=61)
    )
    with pytest.raises(ResendError) as refused:
        otp.resend(challenge, "ana@example.com")
    assert refused.value.wait == 0


def test_comparison_is_constant_time_for_real_and_missing_challenges(sent, monkeypatch):
    calls = []
    real = otp.hmac.compare_digest
    monkeypatch.setattr(otp.hmac, "compare_digest", lambda a, b: calls.append(1) or real(a, b))
    challenge, code = start(sent)
    otp.verify(challenge.pk, PURPOSE, code)
    otp.verify("00000000-0000-0000-0000-000000000000", PURPOSE, code)
    assert len(calls) == 2


def test_decoy_challenge_behaves_like_a_real_one_but_delivers_nothing(sent):
    challenge = otp.start(PURPOSE, channel="email", destination=None)
    assert sent == []
    assert challenge.user is None
    assert otp.verify(challenge.pk, PURPOSE, "123456")[0] is VerifyStatus.WRONG
    with pytest.raises(ResendError):
        otp.resend(challenge, None)  # same cooldown as a real challenge


def test_recovery_goes_to_the_verified_contact_or_becomes_a_decoy(sent):
    profile = make_student()
    user = claim(profile, contact_email="Real.Person@Example.com")
    challenge = otp.start_recovery(PURPOSE, user)
    assert challenge.user_id == user.pk
    assert sent[-1].destination == "Real.Person@Example.com"
    sent.clear()
    assert otp.start_recovery(PURPOSE, None).user_id is None
    assert otp.start_recovery(PURPOSE, claim(make_student())).user_id is None  # no contact on file
    assert sent == []


def test_purge_removes_old_challenges(sent):
    old, _ = start(sent)
    OneTimeCode.objects.filter(pk=old.pk).update(created_at=timezone.now() - timedelta(days=2))
    fresh, _ = start(sent)
    assert otp.purge_stale() == 1
    assert OneTimeCode.objects.filter(pk=fresh.pk).exists()

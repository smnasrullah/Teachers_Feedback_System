"""When results may be shown, and how (BLUEPRINT §5.2 A3-A5).

Results are released only after the round closes, any slice with fewer than
``min_responses()`` responses stays hidden (comment lists too), and comments are listed in a
stable order derived from a server secret, never in the order they were written.
"""

from operator import attrgetter

from django.utils import timezone
from django.utils.crypto import salted_hmac

from apps.core.services import system_settings
from apps.feedback.models import Answer, FeedbackResponse

MIN_RESPONSES_FLOOR = system_settings.MIN_RESPONSES_FLOOR
COMMENT_ORDER_SALT = "apps.feedback.comment_order"
COMMENT_HANDLE_SALT = "apps.feedback.comment_token"
COMMENT_TOKEN_LENGTH = 32


def min_responses() -> int:
    """The configured ``MIN_RESPONSES``, never below the floor."""
    return max(MIN_RESPONSES_FLOOR, system_settings.get("MIN_RESPONSES"))


def enough_responses(count: int) -> bool:
    return count >= min_responses()


def results_visible(window, now=None) -> bool:
    """Results of ``window`` reach teachers and HODs only once it has closed (and never while
    the Admin holds them back)."""
    if system_settings.get("RESULTS_VISIBLE") != "after_close":
        return False
    return window.has_closed(now or timezone.now())


def comment_token(answer_id, offering, window) -> str:
    """An opaque handle for one comment on a page, so a teacher can report it without the
    page carrying the answer's own id. It is not the id and cannot be turned back into it."""
    return salted_hmac(COMMENT_HANDLE_SALT, f"{offering.pk}:{window.pk}:{answer_id}").hexdigest()[
        :COMMENT_TOKEN_LENGTH
    ]


def stable_shuffle(items, *, offering, window, key=attrgetter("pk")) -> list:
    """``items`` in an order keyed by offering, round and each item's ``key``.

    The order is the same on every request, so pagination works, but it is unrelated to the
    order rows were written and cannot be predicted without the server secret.
    """
    scope = f"{offering.pk}:{window.pk}:"
    return sorted(
        items, key=lambda item: salted_hmac(COMMENT_ORDER_SALT, scope + str(key(item))).digest()
    )


def comments(offering, window, question, *, now=None) -> list[str] | None:
    """The comments on ``question`` in stable order, or ``None`` while they must stay hidden
    (round still open, or fewer responses than the threshold)."""
    if not results_visible(window, now):
        return None
    if not enough_responses(
        FeedbackResponse.objects.filter(offering=offering, window=window).count()
    ):
        return None
    answers = (
        Answer.objects.filter(
            response__offering=offering,
            response__window=window,
            question=question,
            encrypted_text__isnull=False,
        )
        .shown()
        .only("id", "encrypted_text")
    )
    return [
        answer.encrypted_text
        for answer in stable_shuffle(answers, offering=offering, window=window)
    ]

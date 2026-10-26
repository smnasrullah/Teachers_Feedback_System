"""The comments of one text question: tagged, searched, filtered and paged.

The list itself comes from ``analytics.comment_list`` (released rounds only, threshold applied,
stable shuffle). A search or tag narrows it, and the narrowed slice must meet the threshold
too: a handful of matches could be told apart by elimination, so they stay hidden.
"""

from dataclasses import dataclass
from urllib.parse import urlencode

from django.core.paginator import Page, Paginator

from apps.analytics import services as analytics
from apps.analytics.services import InsufficientData, Sentiment
from apps.feedback.services import anonymity, wordlist

PAGE_SIZE = 10
MAX_SEARCH_LENGTH = 100
TAGS = frozenset(tag.value for tag in Sentiment)


@dataclass(frozen=True)
class CommentQuery:
    search: str = ""
    tag: str = ""
    page: int = 1

    @classmethod
    def parse(cls, params) -> "CommentQuery":
        tag = params.get("tag", "")
        try:
            page = max(1, int(params.get("page", 1)))
        except ValueError:
            page = 1
        return cls(
            search=params.get("q", "").strip()[:MAX_SEARCH_LENGTH],
            tag=tag if tag in TAGS else "",
            page=page,
        )

    @property
    def narrowed(self) -> bool:
        return bool(self.search or self.tag)

    def encoded(self, page: int) -> str:
        """Query string that selects ``page`` of this search and tag."""
        params = {"q": self.search, "tag": self.tag, "page": page}
        return urlencode({key: value for key, value in params.items() if value})


@dataclass(frozen=True)
class CommentPanel:
    question: object
    query: CommentQuery
    comments: tuple = ()
    page: Page | None = None
    total: int = 0
    notice: object = ""
    previous_query: str = ""
    next_query: str = ""


def _panel(question, query, **fields) -> CommentPanel:
    return CommentPanel(question=question, query=query, **fields)


def comment_panel(
    window, offering, question, query, *, viewer, now=None, everything=False
) -> CommentPanel:
    """The panel for ``question``; ``everything`` lists all comments on one page (print view)."""
    listed = analytics.comment_list(window, offering, question, viewer=viewer, now=now)
    if isinstance(listed, InsufficientData):
        return _panel(question, query, notice=listed.message)
    comments = [comment for comment in listed if comment.text.strip()]
    total = len(comments)
    if everything:
        return _panel(question, query, comments=tuple(comments), total=total)
    if query.tag:
        comments = [comment for comment in comments if comment.sentiment == query.tag]
    if query.search:
        needle = wordlist.fold(query.search)
        comments = [comment for comment in comments if needle in wordlist.fold(comment.text)]
    if query.narrowed and 0 < len(comments) < anonymity.min_responses():
        return _panel(
            question,
            query,
            total=total,
            notice=analytics.NOT_ENOUGH_MESSAGE,
        )
    page = Paginator(comments, PAGE_SIZE).get_page(query.page)
    return _panel(
        question,
        query,
        comments=tuple(page),
        page=page,
        total=total,
        previous_query=query.encoded(page.number - 1) if page.has_previous() else "",
        next_query=query.encoded(page.number + 1) if page.has_next() else "",
    )

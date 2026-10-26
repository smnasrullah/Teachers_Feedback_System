"""The answer filter every comment passes before it is stored (BLUEPRINT §5.2 A8).

``clean()`` is the single entry point ``submit_feedback`` calls. This version keeps the text
as written; the word-list, PII and junk layers plug in behind the same signature.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class CleanResult:
    text: str
    removed_count: int = 0
    flagged: bool = False
    reasons: tuple[str, ...] = ()

    @property
    def empty(self) -> bool:
        """Nothing meaningful is left to store."""
        return not self.text.strip()


def clean(text: str) -> CleanResult:
    return CleanResult(text=text)

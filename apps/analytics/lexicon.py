"""Word lists behind the approximate comment sentiment and the keyword counts (EN + BN).

Deliberately small and plain: a tag from a word list is a rough hint, never a verdict, and the
screens label it "approximate". Words are compared folded (``wordlist.fold``) and without the
common Bangla case endings, so ``ভালোটা`` still counts as ``ভালো``.
"""

POSITIVE = frozenset(
    {
        "good", "great", "excellent", "helpful", "clear", "amazing", "best", "friendly",
        "nice", "patient", "supportive", "engaging", "organized", "organised",
        "knowledgeable", "inspiring", "wonderful", "perfect", "easy", "interesting",
        "punctual", "respectful", "love", "enjoy", "enjoyed", "informative", "fantastic",
        "outstanding", "brilliant", "thorough", "understandable", "motivating", "regular",
        "ভালো", "ভাল", "চমৎকার", "দারুণ", "সুন্দর", "সহায়ক", "বন্ধুত্বপূর্ণ", "ধৈর্যশীল",
        "অসাধারণ", "সেরা", "উপকারী", "আন্তরিক", "যত্নশীল", "মনোযোগী", "পরিষ্কার", "সহজ",
        "প্রাণবন্ত", "নিয়মিত", "সুশৃঙ্খল", "আকর্ষণীয়", "প্রশংসনীয়", "দক্ষ", "সহযোগিতা",
    }
)  # fmt: skip

NEGATIVE = frozenset(
    {
        "bad", "poor", "boring", "confusing", "unclear", "late", "rude", "worst",
        "difficult", "slow", "unprepared", "unhelpful", "disorganized", "disorganised",
        "terrible", "waste", "absent", "irregular", "lack", "lacking", "hard", "impatient",
        "unfair", "biased", "noisy", "awful", "useless", "confused", "disappointing",
        "খারাপ", "বাজে", "বিরক্তিকর", "অস্পষ্ট", "কঠিন", "দুর্বল", "অনিয়মিত", "দেরি",
        "অগোছালো", "রুক্ষ", "সমস্যা", "অসহযোগিতা", "পক্ষপাত", "ধীর", "অনুপস্থিত", "বোরিং",
        "হতাশাজনক", "অপ্রস্তুত", "অসন্তুষ্ট",
    }
)  # fmt: skip

# English negators come before the word ("not good"); the Bangla ones follow it ("ভালো না").
# "don't" is cut at the apostrophe into "don" + "t", hence the truncated forms.
NEGATORS_BEFORE = frozenset(
    {
        "not", "no", "never", "cannot", "without", "don", "doesn", "didn", "isn", "wasn",
        "aren", "weren", "won", "couldn", "wouldn", "hardly",
    }
)  # fmt: skip
NEGATORS_AFTER = frozenset({"না", "নয়", "নেই", "নি"})
NEGATION_REACH = 2

# Case endings and suffixes Bangla words carry; stripped one at a time when looking a word up.
BANGLA_SUFFIXES = ("গুলো", "ভাবে", "টা", "টি", "ের", "র", "ও", "ই", "ে")
MIN_STEM = 2

STOPWORDS = frozenset(
    {
        "the", "and", "for", "are", "was", "were", "with", "this", "that", "have", "has",
        "had", "but", "not", "you", "all", "any", "can", "our", "out", "very", "too", "also",
        "from", "they", "their", "them", "his", "her", "she", "him", "its", "what", "when",
        "who", "how", "why", "will", "would", "could", "should", "just", "more", "much",
        "some", "than", "then", "there", "these", "those", "been", "being", "into", "about",
        "sir", "madam", "teacher", "class", "course", "does", "did", "doesn", "didn", "don",
        "এবং", "ও", "এই", "এটা", "এটি", "সেই", "যে", "যা", "তার", "তাদের", "আমি", "আমরা",
        "আমাদের", "আমার", "তিনি", "তারা", "করে", "করা", "হয়", "হচ্ছে", "আছে", "থেকে",
        "জন্য", "সাথে", "মতো", "খুব", "একটু", "কিন্তু", "অনেক", "স্যার", "ম্যাডাম", "ক্লাস",
        "কোর্স", "না", "নয়", "নেই", "হবে", "দিয়ে", "কিছু", "সব", "আর", "তবে",
    }
)  # fmt: skip

# P13 — Analytics services
**ROLE:** Data-focused backend engineer.
**CONTEXT:** Responses exist. Read CLAUDE.md rule 6 and BLUEPRINT §5.2.
**TASK:** `analytics/services.py` (pure functions, query-optimised, cached with invalidation on submit/close):
- per-question: count, average, distribution, percentage per choice
- per-category score, response rate (receipts count vs enrolled)
- trend by round/semester, department average (anonymised)
- text: sentiment tag (EN+BN lexicon-based, no external API, labelled "approximate"), top keywords, word-cloud data
- every function returns `InsufficientData` below `MIN_RESPONSES` (also for text lists and for filtered slices) and refuses before the window closes unless the caller is Admin with the explicit "live" flag
**CONSTRAINTS:** No query may join response to student/receipt. Indexes added.
**ACCEPTANCE:** Tests with fixtures for each function, threshold + release-after-close behaviour, query-count assertions.
**STOP:** Commit, then stop.

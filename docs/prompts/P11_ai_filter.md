# P11 — Answer filter (abusive / empty text removal)
**ROLE:** NLP-minded backend engineer.
**CONTEXT:** P09 hook exists. Read BLUEPRINT §1 filter row and §5.2 A8.
**TASK:**
1. `feedback/services/filter.py` with `clean(text) -> CleanResult(text, removed_count, flagged, empty, reasons)`; pipeline:
   a. Normalise: Unicode NFC/NFKC (Bangla), strip zero-width characters, lowercase, collapse repeats ("fuuuuck"), leetspeak map.
   b. Word-list + regex layer: `data/filter/en.txt`, `bn.txt`, `banglish.txt`, admin-extendable and allow-list aware. **Token-boundary matching** (Bangla has no `\b`) to avoid false positives inside innocent words. If you prefer not to write explicit terms yourself, ship a short starter list and the admin screen/files for the owner to extend.
   c. PII scrubber: phone numbers (BD formats), e-mails, ID-like digit runs, URLs -> removed.
   d. Junk heuristics: empty, only symbols/digits, keyboard-mash, very low letter ratio.
   e. Optional `AiModerationBackend` interface; `NullBackend` default; `AnthropicBackend` behind env flag `FILTER_AI_ENABLED`, sends only the comment text (never identity), with timeout and fail-open to layers a–d.
2. Action per `PROFANITY_ACTION` (default `remove`: delete offending words, keep the rest). If nothing meaningful remains: optional text -> store no comment but keep ratings; **required** text -> return `reasons` so the form can ask the student to rewrite. Expose `preview_clean()` (no storage) for the form's pre-check. Keep `flagged_count`.
3. Wire into `submit_feedback`. Admin screen: manage words and allow-list, view flagged items (cleaned text only).
**ACCEPTANCE:** Tests for EN/BN/Banglish abuse, obfuscation, boundary false-positives, PII removal, empty/gibberish, clean text unchanged, required-text behaviour, AI backend mocked (timeout fail-open).
**STOP:** Commit, then stop.

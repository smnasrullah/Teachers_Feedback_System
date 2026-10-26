# Support prompts (je kono somoy)

**Resume (Claude Code majhpothe thamle)**
```
Continue the previous prompt. Run git status and the test suite, list what is done and what is left in 5 lines, then finish it.
```

**Bug fix**
```
Bug: <describe>. Steps: <steps>. Expected: <x>. Actual: <y>.
Write a failing test first, find the root cause (3 sentences), fix minimally, run ruff + pytest, commit `fix(<scope>): ...`.
```

**Change one thing only**
```
Change only <element> in <file/page>: <what>. Touch nothing else. Run lint + tests. Reply in 3 lines.
```

**Load my questions**
```
Load docs/QUESTION_BANK.md into the question bank with load_questions and report skipped rows.
```

**Design tweak (look & feel)**
```
Open design/<page>.html and the matching Django template. Make the template match the design exactly at 360px and 1440px, light and dark. Change only templates/CSS. Reply in 3 lines.
```

**Code review (before release)**
```
Act as a strict staff engineer. Review the last N commits for: anonymity leaks (BLUEPRINT §5.2), permission gaps, N+1 queries, hardcoded colours/strings, missing tests, security. Output Blocker/Major/Minor with file:line and fix. Don't change code until I approve.
```

**Anonymity audit (run after P09, P13, P17 and before release)**
```
Try to re-identify one student's feedback using only what a malicious Admin, HOD or Teacher can see in the UI, exports, audit log and database schema. List every path you find (joins, timestamps, ordering, counters, small classes). Fix with tests.
```

**Add a new feature safely**
```
Add <feature>. First list affected files and the permission/anonymity impact in 5 lines. Then implement with tests, run lint + tests, commit.
```

**Windows problem**
```
I am on Windows (D:\Git\Teachers_Feedback_System). <command/error>. Give the PowerShell-compatible fix, update scripts/dev.ps1 or docs if it is a repo issue, and keep Linux/CI working.
```

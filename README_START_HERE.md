# Teacher Feedback System — Claude Code Kit (v2, reviewed)

## Folder-e ki ache
```
CLAUDE.md                 -> project root-e thakbe (Claude Code nijei pore, choto rakha hoyeche token bachate)
.gitignore .gitattributes .editorconfig -> Windows (CRLF) somossha ar secret leak thekate
design/                   -> `design/index.html` browser-e khulo: student dashboard, feedback form, teacher report, admin/HOD dashboard (Bangla/English, light/dark toggle ache) + tokens.css + fonts
docs/MASTER_PROMPT.md     -> EKTA boro "kickoff" prompt (Claude Code-e paste korar jonno) + autopilot version
docs/BLUEPRINT.md         -> pura design: feature tree, wireframe, ER, anonymity rules, permission, threat model, tokens, working tree
docs/QUESTION_BANK.md     -> tumi pore question/rating bisoy ekhane likhbe (ekhon faka)
docs/SUPPORT_PROMPTS.md   -> bug fix, change request, review, resume prompt
docs/prompts/P01..P21     -> ekta ekta kore build prompt
```
Age `design/` folder-er HTML gulo browser-e khule dekho. Ota-i website-er look. Pochondo na hole bolo, ami bodle dibo; build shuru korar age bodlano shobcheye sosta.

## Prerequisites (Windows)
| Tool | Keno | Note |
|---|---|---|
| Python 3.12 | Django app | `py --version` |
| Git | version control | Git for Windows |
| Docker Desktop (WSL2) | PostgreSQL, Redis, PDF (WeasyPrint) | **Recommended.** Docker chhara PDF export ar concurrency test Windows-e kaj nao korte pare |
| Claude Code | build | Node lage na, project-e Node nai |

## Setup (ekbar) — PowerShell
```powershell
cd D:\Git\Teachers_Feedback_System
git init
# ei kit-er shob file ekhane copy koro: CLAUDE.md, dotfiles root-e; docs/ ar design/ folder tader jaygay
claude
```
> PowerShell 5-e `&&` kaj kore na. Ek line-e ekta command likho ba PowerShell 7 use koro.

## Kivabe build korbe — 2-ta path
**Path A (recommended, kom bhul):** prottek prompt-e ei loop
1. `/clear` (notun context, token bache)
2. Bolo: `Execute docs/prompts/P01_scaffold.md`
3. Claude sesh hole nije check koro: `scripts\dev.ps1 test` ar browser-e dekho
4. Thik thakle commit hoyeche kina dekho (`git log -1`), tarpor porer prompt

**Path B (sob ekbare):** `docs/MASTER_PROMPT.md`-er "Autopilot" prompt paste koro. Claude P01 theke P21 porjonto ekta ekta kore chalabe, prottek step-e test + commit, fail korle thambe. Lamba cholbe, tai majhe majhe dekhte thako.

**Plan Mode** (Shift+Tab duibar) shudhu **P08, P09, P12** e use koro, plan ok hole approve koro.

## Token bachanor niyom
| Ki korbe | Keno |
|---|---|
| Prottek prompt-er age `/clear` | Purano context bonayo na |
| Ekbare ekta prompt, ekta slice | Choto kaj = kom bhul, kom retry |
| Lamba kaj-e `/compact` | Context choto hoy |
| Bhari prompt (P08, P09, P12, P20) Opus, baki Sonnet | Khoroch ar quality-r balance |
| Question likhte `docs/QUESTION_BANK.md` edit koro | P10-er command diye load hobe, code bodlate hobe na |
| Kono bug hole `SUPPORT_PROMPTS.md`-er Bug prompt | Test diye reproduce kore minimal fix |

## Order
| # | File | Kaj |
|---|---|---|
| 1 | P01_scaffold | Django project, Docker, Tailwind v4, settings, Windows script |
| 2 | P02_design_system | Token, component, base layout, dark mode, i18n |
| 3 | P03_security_core | Encryption, RBAC layer, CSP, log scrubber, hash-chained audit |
| 4 | P04_accounts | User, roles, ID registry, profiles, HOD, activation code |
| 5 | P05_auth_flows | Signup + authenticator (TOTP), login, recovery codes, reset |
| 6 | P06_academics | Semester, course, offering + admin CRUD |
| 7 | P07_import_enroll | CSV import, enrollment, teacher assignment |
| 8 | P08_results_promotion | Result, CGPA, auto promotion |
| 9 | P09_feedback_core | Anonymity architecture + submit service |
| 10 | P10_questions_windows | Question bank, rounds, versioning |
| 11 | P11_ai_filter | Gali/khali answer filter + PII scrub |
| 12 | P12_student_ui | Dashboard + feedback form |
| 13 | P13_analytics | Aggregates, sentiment, threshold |
| 14 | P14_teacher_panel | Teacher report |
| 15 | P15_hod_panel | HOD panel |
| 16 | P16_admin_panel | Admin dashboard, moderation, audit viewer, settings |
| 17 | P17_exports | PDF/Excel/CSV |
| 18 | P18_notifications | Reminders |
| 19 | P19_polish | Bangla, responsive, a11y |
| 20 | P20_security_tests | Pen-test style audit, RBAC matrix, anonymity tests |
| 21 | P21_release | Docker prod, CI, seed, docs |

Resume dorkar hole: `docs/SUPPORT_PROMPTS.md` theke "Resume" prompt.

## Build shuru korar age 5-ta jinis confirm koro (BLUEPRINT §9)
1. "Ekbar-i feedback" mane **prottek course-e prottek round-e ekbar** (round ekta rakhle semester-e ekbar-i).
2. Teacher/HOD feedback result dekhbe **round shesh hoyar por** (anonymity-r jonno).
3. Ekta offering-e ekjon teacher (lab/theory alada offering).
4. Student signup-e ID-r sathe **activation code** lagbe (onno keu tomar ID diye account khule felte parbe na).
5. **Shob role**-er jonno authenticator app (TOTP 2FA) baddhotamulok; e-mail/SMS OTP nei.

## Local-e login korar shomoy authenticator code (shudhu dev)

Prottek account-e login-er por authenticator app-er 6-digit code lage. Local development-e phone chhara code pete:

```powershell
python manage.py totp_code <username>
```

Ei command shudhu `DEBUG=True` ar `DJANGO_SETTINGS_MODULE=config.settings.dev` hole chole; onno settings-e (test, prod) refuse kore. Notun account-e prothome QR scan kore (ba manual key diye) enrol korte hobe; tarpor command-ta current code print kore. Details: `docs/ADMIN_GUIDE.md` ar `docs/SECURITY.md`.

# UI Visual Review Notes (Pass 1 & Pass 2)

1. **Horizontal overflow fixed (360px):** Allowed `.badge` to wrap (`max-width: 100%`) so closed-round status banners on `teacher_report` never overflow 360px screens.
2. **Typography & casing discipline:** Set Bangla body line-height to `1.68` (`1.38` on headings), removed all-caps from `.qcat`, and fixed the `.fq-seg` checkmark glyph (`\2713`).
3. **Landing hero & anonymity matrix:** Added a 3-deep perforated ballot-stub stack with a single load-time `.seal-animate` stamp, 3-step sequence, and a Teachers/HODs/Admins visibility matrix.
4. **Auth split shell & form ergonomics:** Built a desktop 2-column split layout (`auth-shell`/`auth-brand` + `auth-card`), connected 4-step signup track, show/hide password toggle, live 4-bar strength meter, and submit loading state.
5. **Dashboards, stat tiles & quick cards:** Added `.stat-ico` badges, inline SVG `.sparkline` trends, tactile `.quick-card` navigation tiles, `.username` monospace badge, and rebuilt `.heat` category score pills.
6. **Empty states & ballot illustration:** Added an inline perforated ballot SVG illustration (`.empty-illust`) to `components/empty_state.html` and balanced empty dashboard cards (`content-start`).
7. **Feedback form & sealed receipt:** Added 150ms hover/press star micro-interactions, pill-styled numeric rating output, and turned `student/done.html` into a `.stub-sealed` receipt with stamp animation.
8. **Sticky bars & mobile cards (Pass 2):** Switched `.bottomnav` and `.action-bar` from `fixed` to `sticky` so full-page views never overlap content, hid empty mobile table cells, and aligned comment sentiment/report rows.


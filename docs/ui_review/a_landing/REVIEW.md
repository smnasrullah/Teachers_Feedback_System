# Part A self-review (two passes)

Weakest spots found, all fixed and re-shot (screenshots in this folder, motion frames in `../a_motion/`):
1. Template comment printed as text over the hero scene (multi-line `{# #}`): now `{% comment %}`.
2. Old `.role-card { grid-column: span N }` collapsed the role cards into one column: removed, and 82 dead pre-redesign landing rules pruned from `landing.css`.
3. Old `.faq-list` grid placement squeezed the FAQ: removed with the dead rules.
4. Ballot-stub chip covered the walkers in the hero: moved below the arch edge.
5. Walkers and teacher too small to read: figures enlarged about 25 %.
6. Alpona texture sat behind the headline: now fades out towards the text side (mask gradient).
7. Bento art grew huge on a 360 px phone: capped at 150 px high; wide tiles re-balanced on desktop.
8. Timeline was centred under a left-aligned heading: left-aligned.
9. Bangla headings were cramped by negative letter-spacing: reset to 0 with a taller line-height.
10. Nav anchors missed the new demo section: "Try it" added. Demo digits now match the server-rendered ASCII digits.

Checked: no console errors or CSP violations, no horizontal scroll at 360/768/1440, light/dark and bn/en rendered. Loops pause off screen (`is-live` toggles), `prefers-reduced-motion` and `data-motion="off"` both give `animation-name: none`.

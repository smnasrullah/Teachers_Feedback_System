# TFS art direction (Part A)

## Honest critique of the current look (baseline shots in `a_before/`)
1. The art is one white-on-blue monoline campus; it has no colour, depth, light or life, so the brand feels like a wireframe.
2. The hero is mostly empty blue and hairlines; the arch frame is thin and the picture inside is tiny.
3. Landing sections are all the same text-on-band rhythm (trust strip, steps, roles); nothing is illustrated or interactive.
4. The same campus is pasted twice (hero, anonymity band), so the page repeats itself.
5. The "dashboard preview" is the only demonstration of the product, and it is static.
6. No people anywhere: a feedback tool about teachers and students shows neither.
7. Light and dark are the same drawing with inverted strokes; dark mode has no night, no mood.
8. Motion is a single draw-on at load and a stamp; nothing is ambient, nothing responds to the visitor.
9. Auth and app screens (login, student dashboard, teacher report) are clean but flat: no greeting, no warmth, no Bangladeshi context.
10. Empty and error states are tiny line icons with no character.

## Illustration palette (`static/src/art.css`, extends tokens; every colour has a dark counterpart)
- Sky `--art-sky-1/2/3` (pale morning blues to warm horizon); night `--art-night-1/2` (deep indigo). Sun `--art-sun`, moon `--art-moon`.
- Brick `--art-brick` `#b5472f` with shade/light; krishnachura `--art-bloom` `#e2492f`; foliage `--art-leaf`/`--art-leaf-dark`; paper cream `--art-paper` `#fbf1dc`; path sand; lamp glow `--art-lamp`.
- Linework `--art-line` is a deep warm navy at 1.5px, never pure black. Text never sits on art; art sits beside or below text on flat token surfaces.
- Scene layers keep day colours and a night tint overlay fades in over 600ms, so the theme change is a sunset crossfade and not a repaint.

## Style, characters, motion
- Refined flat shapes plus 1.5px linework, three depth layers (far skyline, hall, foreground), soft light via gradients and glow discs. Original generic Indo-Saracenic hall, no real building.
- Characters: simple, modest, diverse students and a teacher; head, hair, top, bottom and skin are CSS variables on the `<use>`. Six poses: walking, reading, waving, holding a ballot slip, thinking, celebrating.
- Cultural touches used sparingly: alpona texture (mask, brand bands only), one rickshaw-art floral divider before the final CTA.
- Motion: transform, opacity and stroke-dashoffset only; ambient scenes 6-60s, interactions 100-250ms; one orchestrated entrance (hero scene); everything loops only while on screen and the tab is visible; reduced-motion and `data-motion="off"` show the static scene.

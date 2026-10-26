# P02 — Design system & base UI
**ROLE:** Senior UI/UX designer + front-end engineer.
**CONTEXT:** P01 done. Read BLUEPRINT §4 and §6. **Open `design/tokens.css` and every `design/*.html`** and reproduce their look and structure faithfully as Django templates/components.
**TASK:**
1. `static/src/tokens.css`: Tailwind v4 `@theme inline` + `@custom-variant dark (&:where(.dark, .dark *))`, tokens exactly as BLUEPRINT §6 (light + dark). Copy the self-hosted Plus Jakarta Sans and Hind Siliguri woff2 files from `design/fonts/` to `static/fonts/` (keep the OFL license file); Bangla-aware font stack as in `design/tokens.css`.
2. Components in `templates/components/`: navbar (logo, language toggle, notification bell, theme toggle, avatar menu), role sidebar (mobile = bottom bar/drawer), card, stat_tile, badge, button, input, select, textarea, modal, toast, breadcrumb, empty_state, skeleton, progress_ring, star_rating (radiogroup semantics, keyboard + touch, shows numeric value), data_table (degrades to cards on mobile), pagination, chart wrapper (Chart.js with token colours).
3. Layouts: `public.html`, `dashboard.html`, `auth.html`. Landing page (hero, how it works, anonymity promise, roles, FAQ, footer). Error pages 403/404/500.
4. Language switch (Django `set_language`), theme toggle persisted (cookie) and applied before first paint **by an external script** (no inline JS), skip-to-content link.
5. Dev-only `/dev/gallery` (DEBUG only) showing every component in every state.
**CONSTRAINTS:** Tokens only, no hardcoded colours/spacing. 44px touch targets, visible 3px focus rings, `prefers-reduced-motion`, never colour alone, no inline `<script>`/`style=`.
**ACCEPTANCE:** Gallery renders at 360px and 1440px, light and dark, no horizontal scroll; lint + tests pass.
**STOP:** Commit, then stop.

# Art assets

All art is original, inline SVG or a small static SVG. Illustrators can replace any file; keep its class names (they carry colour and motion) and its `viewBox`.
Colours come from CSS variables in `static/src/art.css` (`--art-*`, `--p-*`), never hardcoded. Animations are CSS classes (`.a`, `.bn-*`, `.sec-*`, `.cl1`, `.walker`, ...), so a replacement drawing gets motion by reusing the class on the matching group.

## Rules for every asset
- Under 60 KB (the tests enforce it), SVGO-style: no editor metadata, no `<style>`, `<script>`, `style=""`, `on*=` handlers, raster images or external URLs.
- Decorative: the SVG is `aria-hidden="true"`; the meaning is always in the text next to it.
- Line weight 1.4 to 1.5 px (`--art-line`), flat fills, 1.5 px linework, no gradients except the scene's sky and glow discs.
- Looping motion goes on classes inside a `.live` root; the page script pauses it off screen and when the tab is hidden. The resting (un-animated) pose must read well, because reduced-motion users see it.

| Asset | Size | Used in | Specification for a replacement |
|---|---|---|---|
| `templates/components/illustrations/scene_campus.html` | 12.7 KB | Landing hero (arch frame) | `viewBox 0 0 480 560`, portrait, cropped by the arch (`slice`). Keep the layer groups in order: sky (`.day`/`.night`), `.sun`, clouds, birds, far skyline `.L1`, hall and tower `.L2`, trees `.L3`, ground `.L4`, walkers `.L5`, `.tint`, `g.night` (moon, stars), `.lit` (window and lamp glow). Day colours only; the night look is the `.tint` overlay plus `.night` and `.lit` fading in. Clock hands `.hand` rotate about the clock centre. Gradient ids `sc-*`: include once per page. Generic Indo-Saracenic hall, no real building. |
| `templates/components/illustrations/people.html` | 9.1 KB | Landing (timeline, role cards, final call) and the walkers in the scene | Six `<symbol>`s, `viewBox 0 0 64 96`, feet at y 94: `fig-walk`, `fig-read`, `fig-wave`, `fig-ballot`, `fig-think`, `fig-celebrate`. Recolour with `--p-skin --p-hair --p-top --p-bot --p-long --p-glass` on the `<svg>` or `<use>` (palettes `.p-a` to `.p-e`, `.p-t` teacher). Use the `.f-*` classes. Modest clothing, diverse skin tones and hair, friendly faces. Include once per page. |
| `bento_anon.html` | 0.7 KB | Landing bento: "Anonymous by design" | `160x120`. A slip whose name tag slides away while a shield pops in. Classes `.bn-name`, `.bn-pop`. |
| `bento_combined.html` | 0.8 KB | Bento: "Combined results only" | `160x120`. Three bars grow as dots arrive. `.bn-bar`, `.bar1-3`, `.bn-dot`. |
| `bento_onevoice.html` | 0.6 KB | Bento: "One voice per course" | `160x120`. One slip drops into a ballot box. `.bn-drop`. |
| `bento_closed.html` | 0.9 KB | Bento: "Results after the round closes" | `160x120`. Calendar, padlock shackle lifts, chart appears. `.bn-lock`, `.bn-chart`. |
| `bento_five.html` | 0.7 KB | Bento: "Hidden below five answers" | `160x120`. Five dots light up in turn, then a bar fills. `.bn-dot5`, `.e1-5`, `.bn-bar5`. |
| `bento_modes.html` | 0.8 KB | Bento: "Bangla and English, light and dark" | `160x120`. Sun and moon trade places, the letters অ and A trade places. `.bn-sun`, `.bn-moon`, `.g1`, `.g2`. |
| `sec_unlink.html` | 0.5 KB | Security: answers cannot be traced back | `64x64`. Slip and person with a cut line; dashes flow (`.sec-flow`), the cut draws on (`.draw`). |
| `sec_encrypt.html` | 0.4 KB | Security: sensitive data is encrypted | `64x64`. Padlock over scrambled lines; shackle draws on. |
| `sec_password.html` | 0.4 KB | Security: passwords are hashed | `64x64`. Key and scrambled dots; strokes draw on. |
| `sec_phone.html` | 0.6 KB | Security: authenticator app | `64x64`. Phone with a code, signal arcs draw on, dots pulse (`.sec-code`). |
| `sec_nosite.html` | 0.3 KB | Security: nothing from other websites | `64x64`. Globe with a slash that draws on. |
| `sec_screen.html` | 0.5 KB | Security: comments are screened | `64x64`. Speech bubble with a check that pulses. |
| `static/art/alpona.svg` | 1.1 KB | Brand texture: hero and dark bands (CSS `mask`, tinted by `--primary` / `--on-band`) | `96x96` seamless tile, black strokes on transparent, alpona-inspired (lotus, dots, diamonds). Shown at 6 to 12 % opacity, never behind body text on the hero. |
| `static/art/rickshaw_border.svg` | 1.2 KB | Floral divider above the final call (CSS repeat-x) | `120x48` seamless tile, flat rickshaw-art colours (red, saffron, green, blue, cream) that read on both themes. Use once or twice per page at most. |

Legacy line-art (`campus_line.html`, `vignette_*.html`) still serves the sign-in panel and empty states until Part C and B replace them.

## Runtime
- `static/js/art.js`: pauses loops off screen and when the tab is hidden, `.reveal` fade-in, pointer parallax on `[data-parallax]`. Off for `prefers-reduced-motion` and `<html data-motion="off">`.
- `static/js/demo.js`: the "See what your teacher sees" demo. Local only, nothing is sent.

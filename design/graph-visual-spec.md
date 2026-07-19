# DocMesh — Graph Visual Spec

Companion to `design/graph-mockup.html`. Maps every visual treatment in the mockup to the
real components so the look can be ported 1:1 into @xyflow/react + d3-force + Tailwind v4.
Direction: **dark/technical, Obsidian-meets-Linear** — deep slate canvas, one violet accent,
Inter UI with mono micro-labels, 8px radius family, glow-as-elevation (never heavy shadows).

---

## 1. Tokens

### Core system (existing @theme — unchanged)

| Token | Value |
|---|---|
| `--bg` | `#0f1117` |
| `--surface` | `#161922` |
| `--border` | `#262b38` |
| `--accent` | `#7c5cff` |
| `--text` | `#e6e8ee` |
| `--muted` | `#8b91a3` |

### Derived neutrals (add to @theme)

| Token | Value | Use |
|---|---|---|
| `--sunken` | `#0c0e14` | below-surface wells: chunk cells, tracks, ghost search bg |
| `--raised` | `#1c2030` | hover surfaces, skeleton blocks |
| `--border-strong` | `#323950` | tooltip border, hover borders |

### Signal colors (edge = dominant signal) — 3 hues reserved off the topic wheel

| Token | Hex | Signal | Bright variant (dash-flow) |
|---|---|---|---|
| `--sig-sem` | `#a48fff` | semantic (cosine) — violet, accent family | `#cfc3ff` |
| `--sig-ent` | `#3dc9de` | entity (shared NER) — cyan | `#9fe9f4` |
| `--sig-top` | `#e8a33d` | topic (cluster affinity) — amber | `#ffd28a` |

`--sig-top` amber doubles as the app's **warning** color (Stale badge) — one amber, not two.

### Topic palette (8 slots, node cluster tints)

Hues chosen to never collide with the 3 signal hues (violet 265°, cyan 189°, amber 38° at
high chroma) or with each other; slots 7–8 are low-chroma so they stay distinct from their
high-chroma hue neighbors. All land ~equal perceived lightness on `#0f1117`.

| Slot | Token | Hex | Hue | Mock label |
|---|---|---|---|---|
| 1 | `--t1` | `#5ea2ff` | blue | Finance |
| 2 | `--t2` | `#4ac97e` | green | Markets |
| 3 | `--t3` | `#a5bd52` | lime | Research |
| 4 | `--t4` | `#f07a5e` | coral | Customers |
| 5 | `--t5` | `#ea6188` | rose | Growth |
| 6 | `--t6` | `#d964c9` | magenta | Brand |
| 7 | `--t7` | `#8ca0c6` | steel (low-chroma blue) | Ops |
| 8 | `--t8` | `#c9a87a` | sand (low-chroma amber) | Legal |

**Rule: topic colors are never used as fills.** They appear only via `color-mix()` tints
(5–25% into surface/border/transparent) and as small solid dots/glyphs. That's what keeps
8 colors + 3 signals + 1 accent feeling like one product instead of a crayon box.

### Radius family (8px base)

| Token | Value | Use |
|---|---|---|
| `--r-sm` | 6px | icon tiles (7px ok), marks, kbd |
| `--r-md` | 8px | buttons, inputs, chunk cells, list rows |
| `--r-lg` | 10px | nodes, tooltip, explanation card |
| `--r-xl` | 12px | panels, meta bar, legend, minimap, frames |
| pill | 999px | badges, chips, progress pill, chunk-count badge |

### Type

- UI: `Inter, ui-sans-serif, system-ui, "Segoe UI"` — weights 500/600/650, headings
  letter-spacing `-0.01em…-0.02em`.
- **Signature detail** (`.klabel`): mono micro-label — `600 10px ui-monospace`,
  `letter-spacing .12em`, uppercase, `--muted`. Used for every section label, legend title,
  panel kicker, pair header. All numerals `font-variant-numeric: tabular-nums` in mono.

---

## 2. Component map

### `GraphCanvas`
- Container bg `--bg`; dot grid: `background-image: radial-gradient(circle, #1e2331 1px, transparent 1px); background-size: 24px 24px;` (in react-flow: replace `<Background/>` dots with these values, gap 24, size 1, color `#1e2331`).
- Overlay (non-interactive `::after`): center ambience `radial-gradient(1100px 700px at 46% 40%, rgba(124,92,255,.045), transparent 62%)` + edge vignette `radial-gradient(140% 110% at 50% 50%, transparent 55%, rgba(8,9,13,.55) 100%)`.
- Kill all react-flow default attribution/edge/node styling; `color-scheme: dark`.

### `DocNode`
- Card: `bg: color-mix(in oklab, var(--tc) 5%, var(--surface))`; border 1px `color-mix(in oklab, var(--tc) 22%, var(--border))`; radius `--r-lg`; base shadow `0 1px 2px rgba(0,0,0,.35), 0 6px 16px rgba(0,0,0,.25)`; cursor grab.
- Layout: flex row — icon tile / name+meta column / chunk badge.
- Icon tile: square `--icon`, radius 7px, `bg color-mix(--tc 13%, transparent)`, glyph `color: var(--tc)`. Glyph = one shared sheet+fold SVG (stroke 1.5) with a 6px bold `<text>` type label (PDF/DOC/TXT/MD) — one icon family, one stroke width.
- Name: 600 weight, `letter-spacing -.01em`, ellipsis truncation. Meta line: mono uppercase `--muted` ("PDF · 1.8 MB").
- Chunk badge: pill, mono 10px 600, `bg color-mix(--tc 14%, transparent)`, `color color-mix(--tc 78%, #fff)`.
- **Size scale** (node size = document size; badge shows chunk count):

  | Tier | Bytes | W×H | name fs | icon | meta fs |
  |---|---|---|---|---|---|
  | S | < 50 KB | 148×44 | 11px | 22px | 8.5px |
  | M | < 250 KB | 176×52 | 12px | 26px | 9px |
  | L | < 1 MB | 204×58 | 12.5px | 30px | 9.5px |
  | XL | ≥ 1 MB | 236×66 | 13.5px | 34px | 10px |

  `sizeTier(bytes) = bytes < 50_000 ? 's' : bytes < 250_000 ? 'm' : bytes < 1_000_000 ? 'l' : 'xl'`
- Topic color: node gets class/style `--tc: var(--t{k})` from its dominant cluster slot (`k = clusterIndex % 8`).
- **Hover/selected glow**: `translateY(-2px)`; border → `color-mix(--tc 48%, var(--border))`; shadow → `0 0 0 3px color-mix(--tc 13%, transparent), 0 0 28px color-mix(--tc 22%, transparent), 0 10px 28px rgba(0,0,0,.45)`. 160ms, ease-out-expo.
- **Dim state** (query mode, non-hit): `opacity: .15`, transition 240ms ease-out. Hit nodes run `pulse-once` (below).

### `ConnectionEdge`
- Cubic bezier (react-flow `getBezierPath` is fine), `stroke-linecap: round`, `fill: none`.
- **Thickness = combined score**: `strokeWidth = 1 + combined_score * 4` (range ≈ 1.25–5px).
- **Color = dominant signal**: stroke `--sig-sem` / `--sig-ent` / `--sig-top` at `stroke-opacity: .5` resting, `.9` hover, `.95` selected.
- **Hover/selected treatment** (3 stacked paths, same `d`):
  1. glow: same color, `stroke-width 12`, opacity `.14`
  2. base: as above at full opacity
  3. flow: bright variant color, width 2, `stroke-dasharray: 7 9`, `animation: dash-flow .9s linear infinite` → `stroke-dashoffset: -16` (one dash period = seamless loop).
- Dim state (query mode, non-hit): group `opacity: .08`.

### `EdgeTooltip`
- 184px card, `--surface` bg, 1px `--border-strong`, radius `--r-lg`, shadow `0 4px 12px rgba(0,0,0,.4), 0 16px 40px rgba(0,0,0,.35)`, 8px rotated-square caret.
- Content: mono score `650 15px` + "combined score" caption; three rows of 7px signal dot / label / tabular value. Fade in 200ms.

### `GraphLegend`
- Bottom-left floating card: `color-mix(in srgb, var(--surface) 88%, transparent)` + `backdrop-blur(12px)`, 1px `--border`, radius `--r-xl`, padding 12/14, width ~178px.
- Signal rows: 20px rounded line swatch (3px semantic / 2px others — echoes thickness encoding), 11.5px label, mono hint right-aligned.
- Topic strip: `.klabel` "Topics" + eight 9px dots with `title` tooltips.

### `GraphMetaBar`
- Floating bar: `top/left/right 16px`, h 52, same glass recipe as legend, radius `--r-xl`, shadow `0 8px 24px rgba(0,0,0,.25)`, gap 14, 1px×20px vertical dividers.
- Brand: 18px violet 3-node mesh mark + "DocMesh" 650.
- Stats: 12px muted, bold tabular counts, 3px dot separators.
- **Stale badge**: pill, mono 10px uppercase, amber — `color --sig-top`, `bg color-mix(--sig-top 11%, transparent)`, border `color-mix(--sig-top 28%, transparent)`, 5px dot.
- **Recompute**: ghost button — h 30, radius `--r-md`, 1px `--border`, transparent bg; hover `--raised` + `--border-strong`; active `translateY(1px)`. (Button system: this ghost + the accent-tinted variant in the empty state are the only two variants on this screen.)
- **Progress pill**: h 30 pill, `--sunken` bg; 12px violet arc spinner (`spin 1s linear`), 11.5px muted label, mono count, 56×3px track with `--accent` fill + `fill-breathe` opacity pulse 1.6s.
- **Ghost search slot**: 230×32, radius `--r-md`, `--sunken` bg, `opacity .55`, disabled input, `/` kbd chip. Live (query mode): opacity 1, border `color-mix(--accent 55%, var(--border))`, ring `0 0 0 3px color-mix(--accent 14%, transparent)`, kbd swaps to accent mono "n matches".

### MiniMap override (react-flow `<MiniMap/>`)
- 7px-padded glass card (same recipe), inner svg on `--sunken`, radius 6.
- `nodeColor={node => topicHex}` with opacity .55–.75, `nodeBorderRadius 2`; mask/viewport rect: `fill rgba(230,232,238,.03)`, `stroke rgba(230,232,238,.22)`.

### Controls override (react-flow `<Controls/>`)
- Vertical glass card, radius `--r-lg`; 32px buttons, 14px 1.5-stroke icons in `--muted`; hover `--raised` + `--text`; 1px `--border` separators. Zoom in / zoom out / fit only.
- Both minimap+controls live in a wrapper that animates `right: 16px → 428px` (320ms ease-out-expo) when a panel opens.

### `panels/EdgePanel`
- Floating panel (not full-height sheet): `top 84 / right 16 / bottom 16`, w 396, `--surface`, 1px `--border`, radius `--r-xl`, shadow `0 0 0 1px rgba(0,0,0,.2), 0 24px 64px rgba(0,0,0,.45)`. Header fixed, body scrolls (thin scrollbar `--border-strong`).
- Header: violet-tinted `.klabel` kicker "CONNECTION", 15px/650 title "How are these linked?", two topic-tinted doc pills (6px topic dot + truncated name) around a ↔ glyph, ghost close button.
- Sections spaced 22px, each opened by a `.klabel`.

#### `ExplanationCard`
- `bg color-mix(--accent 4%, var(--sunken))`, border `color-mix(--accent 16%, var(--border))`, radius `--r-lg`, 12.5px/1.65 text.
- Source badge: mono 9.5px uppercase pill — **Local LLM**: violet (`--sig-sem` text, accent-tinted bg/border, sparkle icon); **Template**: neutral muted variant on plain `--sunken` card.
- Loading: badge stays, text → three 9px shimmer lines (last 60%).

#### Score breakdown
- Mono `650 22px` score + muted caption; 8px stacked bar, 2px gaps, segments in the 3 signal colors, outer corners pill; rows: 7px dot / label / tabular value / right-aligned %.

#### `EntityChips`
- Pill chips: `bg color-mix(--sig-ent 7%, var(--surface))`, border `color-mix(--sig-ent 22%, var(--border))`, 11px/500 text.
- **Weight**: trailing 6px cyan dot at opacity 1 / .65 / .35 (w1/w2/w3 = weight tier); mono `×n` doc-frequency count.
- **Rare** variant (high-signal entity): stronger tint (`13%` bg, `45%` border), cyan mono "rare" label.
- Hover: border brightens + `translateY(-1px)`, 160ms.

#### `EvidencePairs`
- Pair header: `.klabel` "PAIR n" + right mono "cos 0.91".
- Two-column grid (gap 8): chunk cells on `--sunken`, 1px `--border`, radius `--r-md`, padding 9/10.
- Caption: mono 9px, 5px topic dot (source doc's topic color) + "doc · p.4 · §Section", ellipsis.
- Excerpt: 11px/1.6, color `color-mix(--text 82%, var(--muted))`.
- **Overlap highlight** `<mark>`: `bg color-mix(--accent 24%, transparent)`, `color #d4cbff`, radius 3px, `padding 0 3px`. Always accent violet — overlap is one concept everywhere.

### `panels/NodePanel`
- Same shell. Kicker "DOCUMENT", filename title, mono meta row (type · size · chunks · topic dot+name in topic color).
- Summary: plain 12.5px/1.65 paragraph.
- Top entities: same `EntityChips`.
- Top topics: `chip topic` variant — topic-tinted pill, solid topic dot, mono % share.
- Strongest connections: rows (radius `--r-md`, hover `--raised`) — 7px topic dot of the other doc, name, 48×4px strength bar filled `width: score*100%` in the **dominant signal color**, mono score.

### Skeleton state
- 3–4 ghost node cards: `--surface` bg, `--border`, real node geometry; inner blocks `--raised` with shimmer overlay: `linear-gradient(100deg, transparent 32%, rgba(230,232,238,.055) 50%, transparent 68%)`, `background-size 220% 100%`, `shimmer 1.8s ease-in-out infinite` (background-position 130% → -90%).
- Skeleton edges: `--border` stroke 1.5, `dasharray 4 6`, static.

### Empty state
- Centered: 52px rounded-14 glyph tile (accent-tinted 7% bg / 18% border, violet mesh icon), 14.5px/600 "No connections yet", 12px muted "Upload at least 2 documents to see how they link together." (max 34ch), accent-tinted ghost button "Upload documents". The empty state is the one place the accent tints a button.

---

## 3. Motion spec

Global easings: enter `cubic-bezier(0.16, 1, 0.3, 1)` (ease-out-expo), exit `cubic-bezier(0.7, 0, 0.84, 0)`. Only `transform` + `opacity` animate (plus SVG stroke props). All non-essential motion gated behind `prefers-reduced-motion`.

| Motion | Duration / easing | Detail |
|---|---|---|
| Node hover glow | 160ms ease-out-expo | `translateY(-2px)` + border/shadow glow |
| Panel slide-in | 320ms ease-out-expo (opacity 280ms) | `translateX(16px) → 0`, fade |
| Panel exit | 220ms ease-in | reverse |
| Edge hover brighten | 160–200ms ease-out | stroke-opacity .5 → .9 |
| Edge dash-flow | `.9s linear infinite` | `dasharray 7 9`, offset → −16 (loop-perfect); linear is correct for continuous flow |
| Query dim | 240ms ease-out | non-hits → opacity .15 (nodes) / .08 (edges) |
| Query pulse | **600ms ease-out-expo, once** | box-shadow ring `0 0 0 0` topic@45% → `0 0 0 16px` transparent; re-trigger via class remove/reflow/add |
| Skeleton shimmer | 1.8s ease-in-out infinite | background-position sweep |
| Progress fill breathe | 1.6s ease-in-out infinite | opacity 1 → .6 → 1 |
| Spinner | 1s linear infinite | rotate |
| Buttons/chips micro | 160ms | hover bg/border, `translateY(±1px)` |
| Canvas-ui shift on panel open | 320ms ease-out-expo | wrapper `right` 16 → 428px |

---

## 4. Porting notes

- Every `color-mix(in oklab, …)` works in Tailwind v4 arbitrary values, e.g.
  `bg-[color-mix(in_oklab,var(--tc)_5%,var(--surface))]`; topic slot is injected per node as
  inline `style={{ '--tc': topicHex }}` so one class set serves all 8 slots. Same trick for
  `--sc` (signal color) on connection rows.
- Glass chrome recipe (metabar/legend/minimap/controls/demo surfaces):
  `bg color-mix(in srgb, var(--surface) 88%, transparent)` + `backdrop-blur(12px)` + 1px `--border`.
- The mockup's `.stage` absolute px coordinates simulate a settled d3-force layout; in the app,
  d3-force writes node positions and react-flow renders — all styling above is
  position-independent.
- Dark-only by design for v1 (canvas tool, matches the shipped @theme). If a light theme comes
  later, re-derive tints via the same `color-mix` recipes over light neutrals — do not invert.
- Focus rings: `outline: 2px solid var(--accent); outline-offset: 2px` on all interactive chrome.

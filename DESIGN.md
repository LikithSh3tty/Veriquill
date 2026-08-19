# Design

<!-- impeccable:design-schema 1 -->

Written from the built surfaces, not ahead of them. Two surfaces share one system:
the public page (`ui/index.html`, Persuade) and the review screen
(`ui/review.html`, Operate).

## The one idea

Veriquill's whole claim is that it shows uncertainty instead of hiding it. Both
surfaces are built around the same object — a cohort drawn on a shared axis, where
each candidate is an interval rather than a score, and overlapping intervals are
bracketed as a tie the tool refuses to order.

Everything else is set quietly around that. No cards, no stat tiles, no hero
metric.

## Colour

Restrained: neutrals plus one accent, and the accent means something specific.

| Token | Value | Role |
|---|---|---|
| `--ground` | `#e9edf0` | page ground, cool document stock |
| `--panel` | `#f7f9fa` | lifted panel: gate strip, review margin, specimen |
| `--panel-sunk` | `#dde4e9` | recessed tracks, disabled controls |
| `--rule` | `#c5d0d7` | hairlines between rows |
| `--rule-strong` | `#93a3ae` | axis baselines, input borders, tie bracket |
| `--ink` | `#111a22` | text, and every band the machine measured |
| `--ink-soft` | `#48565f` | secondary text, basis sentences |
| `--human` | `#1f3fd1` | **only** what a human decided |

**Ink is what Veriquill measured; blue is what a human decided.** Blue appears on
review-action verbs in the audit log, the override callout, the caret and text
selection, the focus ring, and the selected-row marker. It appears nowhere else,
so the colour carries the same distinction the audit log does.

Semantic states each carry a word as well as a colour, so colour is never the sole
carrier: `--critical #8a1b2b`, `--high #8f4a11`, `--medium #63541b`,
`--approved #0b6b45`, `--pending #8a1b2b`.

Light ground, chosen from the scene rather than the category: a recruiter at a desk
in daylight with a browser full of white tabs either side of this one.

## Type

- **Interface and body:** Public Sans Variable. One family carries headings,
  labels, buttons, and body on the review screen — a product UI does not need a
  display pairing, and a serif on a data label is costume.
- **Display, public page only:** Bricolage Grotesque Variable, set large and tight
  (`clamp(2.25rem, 5.5vw, 4.25rem)`, tracking `-0.035em`).
- **Data:** JetBrains Mono for every number, path, sha, and axis label, with
  `font-variant-numeric: tabular-nums` so compared figures line up.

Fixed rem scale at ~1.2 (`--text-xs 0.75` → `--text-2xl 1.75`). Not fluid: product
UI is read at consistent DPI, and a heading that shrinks inside a panel looks
worse. Prose measure caps at 58–70ch.

## Layout

- Review screen: sticky gate strip, then a two-column body — cohort left
  (`1.55fr`), candidate panel right (`min 22rem`), collapsing to one column at
  68rem and to a stacked gate at 46rem.
- Public page: single 68rem column, sections separated by hairlines.
- **The axis rule:** the scale row and the data rows share one grid template, so a
  gridline sits exactly under the number that labels it. Anything that insets one
  and not the other — row padding, a tie group's own padding — makes the axis lie
  about position. Both bugs happened; both are fixed by keeping the gutter on the
  container, never on the rows.

## Components

Standard vocabulary, deliberately. Buttons, radios, text inputs, and tables look
like themselves; the invention is spent on the band axis.

- Every control ships default, hover, focus-visible, disabled states. The primary
  button darkens on hover; disabled goes to sunk panel with soft ink.
- Flags are bordered panels with a severity chip, never a coloured left border
  above 1px.
- Loading is a skeleton sweep, not a spinner parked in content.
- Empty states teach: "No candidate has been ranked yet. Rank a cohort to see how
  far apart the evidence actually places them."
- Browser surfaces are themed: `::selection`, `caret-color`, `scrollbar-color`,
  focus ring, and tabular numerals.

## Motion

State only, `160ms cubic-bezier(0.2, 0, 0, 1)`. Background, border, and opacity
transitions; no entrance choreography, and no layout-property animation (animating
`width` was flagged by the detector and removed). `prefers-reduced-motion` reduces
everything to near-zero.

## Voice

Plain, specific, and never overclaiming. Controls name their action ("Dismiss
flag", "Approve revision 0"); errors name the problem and the recovery ("Give a
reason. It goes in the audit log next to your name."). Numbers that were never
measured read "not measured" with the reason beside them, never "0.00". Copy
reaching the screen is written as English, including plurals — the backend's
`1 repositor(y/ies)` was fixed because it was visible to a recruiter.

## Verified at finish

- Impeccable detector over `ui/src`, `index.html`, `review.html`: no findings, with
  the HTML parser modules present so contrast and selectors were actually
  evaluated.
- Axis alignment measured in the browser: scale labels and gridlines identical at
  `240, 424, 608, 793, 977`.
- 41 UI tests, TypeScript clean, both pages build.
- Not verified: rendering at a genuinely narrow viewport. The browser resize did
  not change the rendering viewport, so the mobile rules are reviewed but unproven.

# econcharts — spec grammar (canonical reference)

The frozen vocabulary for hand-authoring charts. This is the contract the manual and
any AI authoring layer build on. Validation happens at the spec boundary (`spec.py`),
with errors naming the offending key.

## Principles
1. **Substance, not form.** A spec carries content + domain semantics only. Every
   formal choice (color, font, spacing, label format) lives in the theme.
2. **Overrides are *selections* from a theme-named set** — never raw values. `color`,
   `line`, `date_label`, and annotation `color/weight/line` all pick a name the theme
   defined. The chart-level `style:` block is the *sole* raw-value escape hatch.
3. **`type` is explicit per series** (no chart default) and is also the combination
   rule (see Series).
4. **Selections cascade** most-general → most-specific:
   **theme default → batch-header default → chart/series override.**
5. **Natural shorthand** where it reads cleanly (`mark: last`, `hline: 0`, `period: 2024`).

---

## Chart spec (top level)
| key | type | notes |
|-----|------|-------|
| `title` | string? | chart title |
| `subtitle` | string? | below the title |
| `source` | string? | drawn as a small footnote at the bottom left (`"Fuente: BCRP"`); omit to suppress |
| `period` | string? | the axis frame / window — see **Period** |
| `theme` | string | default `bbva` |
| `ylabel` | string? | primary y-axis label |
| `y2label` | string? | secondary y-axis label |
| `date_label` | string? | selects a theme date-label style by name — see **Date labels** |
| `legend` | string? | legend position by name, overriding the theme's default — see vocabularies |
| `series` | list | **required**, ≥1 — see **Series** |
| `annotations` | list | optional — see **Annotations** |
| `style` | map | escape hatch: raw rcParam / axis overrides. Rarely touched. |

`id` is added at the batch level (output identity); a standalone chart doesn't need it.

## Series (list item)
| key | type | notes |
|-----|------|-------|
| `name` | string | **required** — identity + default legend text |
| `data` | string \| list \| map | **required** — see **Data** |
| `type` | `line`\|`bar`\|`area`\|`stacked` | **required**, no default |
| `axis` | `primary`\|`secondary` | default `primary` |
| `label` | string? | overrides the legend display name (default = `name`) |
| `mark` | map \| shorthand | data-label marks — see **Mark** |
| `highlight` | map \| shorthand | recolor chosen bars (emphasis); **bar series only** — see **Highlight** |
| `color` | string? | selects a **theme palette color by name** (not hex) |
| `line` | `solid`\|`dashed`\|`dotted` | stroke style; **line series only**; default `solid` |
| `width` | float? | stroke width in points; **line series only**; default = theme rc |

**Combination by `type`** (the type *is* the combine rule): multiple `bar` group
side-by-side (dodged); multiple `stacked` stack (negatives downward); `area` fill and
stack; `line` are smoothed curves drawn on top. Mixing is allowed (e.g. stacked bars +
a total line).

## Mark (per-series data labels)
| key | type | notes |
|-----|------|-------|
| `at` | `all`\|`last`\|token\|[tokens] | which points to mark |
| `marker` | bool | filled dot; **line series only**; default `false` |
| `value` | bool | show the numeric value as a label; default `true` |
| `text` | string? | custom text replacing the value; **single point only** |
| `decimals` | int? | pin decimal places for value labels; default = from Excel cell format, else inferred from data |

Shorthand: `mark: last` or `mark: [2020Q2, 2021Q1]` → `{at: …}`. A line mark needs at
least one of `marker` / `value` / `text`. `mark: last` on a partial series marks **that
series'** last real point (≠ the sample end).

## Highlight (per-series bar emphasis)
| key | type | notes |
|-----|------|-------|
| `at` | `last`\|token\|[tokens] | which bars take the highlight color (`all` is rejected — use `color`) |
| `color` | string? | theme palette color by name; default = the theme's own `highlight` color |

Shorthand: `highlight: last` or `highlight: [2026, 2027]` → `{at: …}`. **Bar series
only** — the BBVA pattern of emphasizing the forecast years or the latest bar within a
(typically single-series) bar chart. Non-highlighted bars keep the series color; a
value-label mark on a highlighted bar takes its bar's color.

## Annotations (list; each a tagged map)
| form | shape | style keys |
|------|-------|-----------|
| `hline` | `hline: 0` or `[0, 2]` | `color`, `weight`, `line` |
| `vline` | `vline: 2020Q2` or `[…]` | `color`, `weight`, `line` |
| `span` | `span: {from, to, label?}` | `color` |
| `band` | `band: {y0, y1, label?}` | `color` |

`vline`/`span` take period tokens. `vline` sits on the period boundary for bar charts,
at the data point for line/area. Annotation `color` is a **separate 3-name role
vocabulary** (`grey`/`orange`/`blue`) that tints per role — distinct from the series
palette names (which mostly coincide, but `grey` differs).

## Data (the `data` value)
- `excel:<file>#<sheet>!<column>` — `<file>` resolves against `data_root`; the period
  column defaults to the sheet's first column. Daily date cells arrive as datetimes.
- inline **list** `[v, v, null, …]` — aligns positionally to the `period` window.
- inline **map** `{2024Q1: 1.2, 2024Q2: null}` — carries its own periods.
- `gsheet:…`, `db:…` — recognized, not yet implemented.
- Missing values (`null`) may sit only at the **ends**; a line starts/ends at its first/
  last real point (no bridging).

## Period (axis frame)
A single token or `start:end` (inclusive). The window is the **authoritative axis
frame**: the chart spans exactly it, even where a series has no data; data outside is
clipped; with no `period`, the axis falls back to the data's own range.

| freq | token | example |
|------|-------|---------|
| year | `YYYY` | `2024` |
| quarter | `YYYYQn` | `2024Q1` |
| month | `YYYYMmm` | `2024M03` |
| day | `YYYY-MM-DD` (ISO) | `2024-03-15` |

Either bound may be a **data-driven token**: `start` = the sample's first period, `end`
= its last (min/max across all dated series, ≠ any one series' first/last). E.g.
`2018Q1:end`, `start:2025Q4`, `start:end`. One frequency per chart.

**Tokens never need quoting.** YAML hands a bare `2024` over as a number and a bare
`2024-03-15` as a date; both are normalized to their string token at the spec boundary —
in `period`, `vline`, `span.from/to`, `mark.at`, `highlight.at`, and inline-map data keys.

---

## Theme-named selection vocabularies
What names a spec may select (the theme owns the values + the default):
- **series `color`** — palette: `blue lightblue green orange yellow cyan purple grey
  red teal gold darkgreen` + `structural ink slate amber`.
- **`line`** (series): `solid` `dashed` `dotted` (annotation `line`: `solid` `dotted`).
- **bar `highlight.color`** — same palette names; omitted → the theme's `highlight`
  color (bbva: `lightblue`).
- **annotation `color`**: `grey` `orange` `blue`; **`weight`**: `thin` `thick`.
- **`date_label`** styles, per display granularity (applied where defined, else default):
  D `plain`(15-jul)/`dotted`(15-jul.) · M `plain`(mar-24)/`dotted`(mar.-24) ·
  Q `month`(mar-24, **default**)/`quarter`(1T24) · Y `full`(2024). The axis chooses the
  granularity adaptively (finest that fits the width; daily→month→quarter→year).
- **`legend` position**: `below` `above` `top-left` `top-right` `bottom-left`
  `bottom-right`. The theme owns the default (`bbva`: `below`; `macro`: `top-left`).
  Override per chart with `legend: top-left`. `below`/`above` are figure-level rows;
  the four corners sit inside the axes. Single-series charts have no legend by default.
- **Number formatting** (theme-only — no per-chart override): `number_format.thousands`
  and `number_format.decimal` set the separators used for value labels and y-axis ticks.
  Both `bbva` and `macro` default to es-PE (`.` thousands, `,` decimal, e.g. `1.234,5`).
  Declared once in the theme YAML; required at parse time.

## Render-time choices (NOT spec fields)
One spec → many targets, chosen at render:
- **size** (physical mm, global defaults): `word_half` 75×60 · `word_full` 117×60 ·
  `slides_half` 85×70 (default) · `slides_full` 140×75. A theme may override these or
  add new names in its own `sizes:` block (e.g. `macro` maps `slides_full` to 200×150 mm
  to match the R export target).
- **backend**: `png` (Slides, dpi=300, transparent) · `svg` (text as `<text>` elements,
  selectable/searchable) · `pdf` (TrueType fonts embedded, `pdf.fonttype=42`).

## Batch document (orchestration; layer above a chart — see roadmap C)
One document renders many charts to separate figures:
```yaml
data_root: ./data            # orchestration: where workbooks live
output_dir: ./figuras        # orchestration: where PNGs land
theme: bbva                  # inheritable default
size: slides_half            # inheritable default
backend: png                 # inheritable default
render: [pbi, inflacion]     # optional id subset; omit = all
charts:
  - {id: pbi, title: …, period: 2018Q1:end, series: […]}
  - {id: inflacion, …}
```
- **Orchestration (header-only):** `data_root`, `output_dir`, `render`.
- **Inheritable (header default → chart override):** `theme`, `size`, `backend`, `date_label`.
- **Pure chart substance:** `id`, `title`, `subtitle`, `source`, `period`, `ylabel`,
  `y2label`, `series`, `annotations`, `style`.
- A chart spec must render **standalone** — it may inherit the four defaults but never
  *require* a header key. Output names: `<id>_<renderdate>.png`.

# econcharts — CLAUDE.md

## Purpose
Automated production of publication-quality economic charts from a minimal, substance-only spec. Form (style, color, layout) is pre-encoded; the user supplies only content, data, per-series chart type, and domain annotations. A narrow DSL for macro time-series charts — deliberately **not** a general grammar of graphics.

## Core principles
- **Spec, not code.** Charts are declared in YAML, validated and resolved by deterministic Python, rendered by a fixed engine. No code generation, no AI in the render path.
- **Substance over form.** The spec carries content + domain semantics only. Every formal choice lives in the theme.
- **Narrowness is the feature.** Resist adding knobs — each new option is drift toward ggplot. The 80% case needs almost nothing; rare cases use the `style:` escape hatch.
- **Domain-semantic vocabulary.** Users write in an economist's terms (`recessions`, `target`), not graphics primitives. The registry that resolves these is the project's differentiator.
- **Hand-authorable first.** The full pipeline must work on hand-written specs before any AI authoring layer exists.

## Pipeline
`YAML spec → pydantic validate → resolve (data refs + registry tokens) → matplotlib render → output backend (png | svg | pdf)`

## Package layout
```
econcharts/
  spec.py          # pydantic v2 models, YAML load + validation
  data.py          # DataResolver; ref grammar; returns long df
  registry.py      # loads domain tokens from registry/*.yaml
  charttypes.py    # per-series renderers: line / bar / area (+ fan later)
  annotations.py   # spans, bands, vline/hline, marks
  theme.py         # theme engine: loads themes/*.yaml, palette, locale/period formatters
  render.py        # orchestration: spec -> Figure -> output backend
  cli.py           # econcharts render spec.yaml -o out.png
themes/
  bbva.yaml        # reference house style (#001391): colors+names, cycle, annotations, rcParams
registry/
  recessions.yaml  # named recession date spans by region
  targets.yaml     # named target bands (e.g. inflation_pe: 1-3%)
  events.yaml      # named dated events for marks
tests/
  baseline/        # pytest-mpl golden images
```

## The spec
`type` is **required per series** (`line` | `bar` | `area` | `stacked`). There is no chart-level type default — type is always explicit. The type is also the *combination* rule: multiple `bar` series **group side-by-side** (dodged); multiple `stacked` series **stack** (negatives stack downward); `area` series are filled; `line` series are smoothed curves.

- **chart-level**: `title, subtitle, source, period, theme, ylabel, y2label`
- **series** (list): `name, data, type, axis` (`primary` | `secondary`, default `primary`), `label?`
- **annotations** (list, optional):
  - `recessions: <region>` — registry → shaded vertical spans
  - `span: {from, to, label?}` — ad-hoc shaded period
  - `band: {y0, y1, label?}` — horizontal shaded band
  - `target: <named>` — registry → band + center line
  - `vline: <date>` / `hline: <value>` — separators; scalar or list
  - `mark: {at, text}` — dated callout
- **escape hatch**: `style: {...}` — raw rcParam / axis overrides, rarely touched.

Example (contribution-to-growth — the canonical combo: stacked bars + total line):
```yaml
title: PBI real — contribuciones al crecimiento
subtitle: var. % anual, puntos porcentuales
source: BCRP
theme: bbva
period: 2018Q1:2025Q4
series:
  - {name: Consumo,     data: "excel:pbi.xlsx#trim!c_consumo",   type: stacked}
  - {name: Inversión,   data: "excel:pbi.xlsx#trim!c_inversion", type: stacked}
  - {name: Sector ext., data: "excel:pbi.xlsx#trim!c_xn",        type: stacked}
  - {name: PBI,         data: "excel:pbi.xlsx#trim!pbi_yoy",     type: line}
annotations:
  - recessions: peru
  - hline: 0
  - mark: {at: 2020Q2, text: COVID-19}
```
The `stacked` components stack into the net total; the `line` (PBI) overlays it.

## Data resolution
Ref grammar, dispatched by prefix:
- `excel:<file>#<sheet>!<column>` — **v1, build first**
- `gsheet:<id>#<tab>!<range>` — later
- `db:<series>?freq=<A|Q|M>` — later; hits tsdb-api at `db.simgol.net`

Resolver contract: **always** returns a tidy/long DataFrame `[period, series, value]`. Excel backend: each sheet has a period/date column (default = first column, configurable) plus named series columns; the ref names the series column. Workbook paths resolve against a configured `DATA_ROOT`. Normalize wide→long here, once, at the boundary.

## Time & locale
- Internal index = pandas `PeriodIndex` with explicit freq (A/Q/M), inferred from data or `period`.
- `period: 2010Q1:2025Q4` (also `2010M01`, `2010`) parses to a window. Either bound may be a data-driven token instead of a date: `start` = the sample's FIRST period, `end` = its LAST (e.g. `2010Q1:end`, `start:2025Q4`, `start:end`), filled from the data — the min/max across all dated series, ≠ any one series' own first/last point.
- `period` is the **authoritative axis frame**: the chart spans exactly that window (xlim + ticks), even where a series has no data; series draw only where they have values (lines start/end at their first/last real point). Data outside the window is clipped; with no `period`, the axis falls back to the data's own range. Framing is done at the axis (not by padding data), so `mark: last` still means the series' own last point, not the frame end. `end` forces a two-phase resolve (read dated data → learn the sample max → materialize the window → align inline-list series → clip) in `render._resolve_framed`.
- es-PE formatting (quarter/month labels, thousands separator) lives in `theme.py` formatters — never in the spec.
- Centralize every date→axis-coordinate conversion in one place; never mix strings / Timestamps / mpl-dates downstream.
- **Time-series-first.** Categorical x supported but secondary; scatter is out of v1 scope.

## Theme
- A theme = one `themes/<name>.yaml` (the single source of truth): a named color table (`colors`), the series `cycle`, the `annotations` color vocabulary, and matplotlib `rc` params (font, spines, grid, legend, sizes). `theme.py` is the engine that loads it, resolves color NAMES→hex everywhere, and applies the rcParams in memory (no `.mplstyle` on disk). Helper formatters + palette cycle live on the resolved `Theme`.
- Colors are named once in `colors:` and referenced by name everywhere else — in `cycle`/`annotations`/`rc` AND in chart specs (`color: orange`, resolved against the full table). **Never hard-code color in renderers** — pull from the active theme.
- `bbva` is the reference theme; primary `#001391` (2025 house palette, extracted from the official `Addin_BBVA_2025.xlam`). Themes are pluggable.
- Form lives *entirely* here. If a formatting choice shows up in a spec, it belongs in the theme.
- **Named output sizes** (the add-in's export presets, physical mm): `word_half` 75×60, `word_full` 117×60, `slides_half` 85×70 (default), `slides_full` 140×75. Size is a render-time choice (one spec → many targets), not a spec field — like the output backend.

## Registry
Domain tokens are data, not code — YAML under `registry/`:
- `recessions.yaml`: `{peru: [{from, to, label?}, ...], us: [...]}`
- `targets.yaml`: `{inflation_pe: {y0: 1, y1: 3, center: 2}}`
- `events.yaml`: named dated marks
The resolver expands a token to geometry + style at load time. Adding a recession period = editing YAML, no code change.

## Renderer & output backends
- One `render(spec) -> Figure`; output is a backend flag on the same figure.
- `png` (Google Slides): `savefig(dpi=300, bbox_inches="tight", transparent=True)`. Fonts rasterize — ensure the font is present at render time.
- `svg` (LaTeX): set `rcParams["svg.fonttype"]="none"`, vector, font matched in LaTeX. PDF backend available as an alternative.
- Annotation mapping: `span`→`axvspan`, `band`→`axhspan`, `vline`→`axvline`, `hline`→`axhline`, `mark`→`annotate`.
- Label collision is matplotlib's real weak spot for automation: use `adjustText` for marks/data labels and tune it per chart type once.

## Conventions
- Python ≥3.11, pydantic v2, YAML specs, matplotlib only for rendering.
- Validation errors surface at the spec boundary naming the offending key — never a raw matplotlib traceback.
- No browser/interactive output; no AI in the render path.
- One responsibility per module, per the layout above.

## Build order
1. `spec.py` + `theme.py` (bbva) + `render.py` for `line` only, `png` backend — render a hand-written spec end to end.
2. `data.py` Excel resolver + long-df contract.
3. `charttypes.py`: bar, area, stacking, secondary axis.
4. `annotations.py` + `registry.py`: recessions, hline/vline, band/target, mark.
5. `svg`/`pdf` backends + es-PE formatters.
6. `cli.py`.
7. Extensions: `fan` type (PyBEAR forecast bands), small multiples / facets, gsheet + db resolvers.
8. AI authoring layer — separate, optional, NL → validated spec. **Build last.**

**Gate:** the pipeline must produce a chart you would publish, from a hand-written spec, before step 8.

## Testing
- `pytest-mpl` golden images per chart type in `tests/baseline/`.
- Schema tests: valid specs parse; malformed specs raise clear errors at the right key.

## Dependencies
Core: `matplotlib, pandas, numpy, scipy, pydantic>=2, pyyaml, openpyxl, adjustText`.
Later resolvers: `gspread, google-api-python-client, requests`.

## Non-goals
- Not a general grammar of graphics (not ggplot / Vega).
- Not interactive / web.
- No per-chart styling in specs beyond the `style:` escape hatch.
- No AI in the render path.

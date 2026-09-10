# econcharts — CLAUDE.md

## Purpose
Automated production of publication-quality economic charts from a minimal, substance-only spec. Form (style, color, layout) is pre-encoded; the user supplies only content, data, per-series chart type, and domain annotations. A narrow DSL for macro time-series charts — deliberately **not** a general grammar of graphics.

## Core principles
- **Spec, not code.** Charts are declared in YAML, validated and resolved by deterministic Python, rendered by a fixed engine. No code generation, no AI in the render path.
- **Substance over form.** The spec carries content + domain semantics only. Every formal choice lives in the theme. Overrides are *selections* from theme-named sets (`color: orange`, `line: dashed`), never raw values; the chart-level `style:` block is the sole raw-value escape hatch.
- **Narrowness is the feature.** Resist adding knobs — each new option is drift toward ggplot.
- **Domain-semantic vocabulary.** Users write in an economist's terms, not graphics primitives. The registry that resolves tokens like `recessions: peru` / `target: inflation_pe` is the planned differentiator (backlog — not yet implemented).
- **Hand-authorable first.** The full pipeline works on hand-written specs; an AI authoring layer is a separate, optional, last-built extension.

## Documents — who owns what
- **GRAMMAR.md** — the **canonical, frozen spec grammar**: every key, vocabulary, and shorthand, including the batch document. When the spec surface changes, GRAMMAR.md is updated in the same change. **Do not duplicate its contents here.**
- **manual.html** — the user manual shipped in the bundle (self-contained HTML).
- **README.md** — public-facing overview + dev quickstart.
- This file — design rationale, architecture, conventions, status.

## Status (feature-complete core; version = pyproject.toml)
Done: line/bar/area/stacked (+ combinations, secondary axis), per-series marks with deterministic label placement, per-series bar `highlight` (emphasis recoloring), hline/vline/span/band annotations, adaptive daily→yearly date axis, authoritative `period` framing with `start`/`end` tokens, Excel + inline data, bbva theme, named export sizes, batch documents → figures + PPTX deck, CLI, frozen Windows exe (ship/), 192 tests incl. golden images.

Backlog (build in this order when asked): domain registry (`recessions:`/`target:`/event marks — `registry/` dir exists but is empty; tokens are YAML data, not code), polished svg/pdf backends (`svg.fonttype: "none"` for LaTeX), gsheet/db resolvers (db hits tsdb-api at `db.simgol.net`), `fan` chart type (PyBEAR forecast bands), facets, slim bundle (drop scipy), AI authoring layer **last**.

## Pipeline
`YAML spec → pydantic validate (spec.py) → resolve data + frame (data.py, render._resolve_framed) → matplotlib render → png | svg | pdf` — and at the batch level: `batch.yaml → per-chart jobs (fail-soft) → figures + .pptx deck`.

## Repo layout
```
econcharts/
  spec.py          # pydantic v2 models, YAML load + validation (the spec boundary)
  data.py          # DataResolver; ref grammar; period parsing; long-df contract
  charttypes.py    # CHART_TYPES strategy classes (draw + mark dispatch per type) + primitives (PCHIP smoothing)
  annotations.py   # hline / vline / span / band overlays
  marks.py         # value-label placement primitives + cross-series line-mark rules
  timeaxis.py      # adaptive date-axis granularity + tick planning (pure)
  theme.py         # theme engine: loads themes/*.yaml; es-PE formatters; named sizes
  render.py        # orchestration: spec -> Figure -> backend; framing; mark finalize
  batch.py         # batch documents: header cascade -> ChartJobs, fail-soft run
  deck.py          # rendered PNGs -> .pptx; plain sheet, or the BBVA slide (chrome)
  cli.py           # econcharts build <batch.yaml> | render <spec.yaml> -o out.png
themes/bbva.yaml   # reference house style — SINGLE SOURCE OF TRUTH for all form
registry/          # (empty — future domain tokens: recessions, targets, events)
examples/          # hand-written specs + datos.xlsx + gallery.yaml batch
tests/             # 9 test files; golden images in tests/baseline/ (pytest-mpl)
ship/              # frozen-exe workstream: econcharts.spec (PyInstaller), build.py, launch.py
```
`bbva source/` holds the original add-in (`*.xlam`) — **never commit it** (gitignored).

## The spec
The full grammar lives in **GRAMMAR.md** — consult it before writing or validating any spec. Essentials: `type` is required per series and is also the combination rule (bars dodge, stacked stack ±, areas fill+stack, lines overlay on top); `mark` is a **per-series field** (`mark: last`, `mark: {at, marker, value, text, decimals?}`), *not* an annotation; annotations today are exactly `hline` / `vline` / `span` / `band`. Canonical combo (stacked contributions + total line):
```yaml
title: PBI real — contribuciones al crecimiento
subtitle: var. % anual, puntos porcentuales
source: BCRP            # drawn as footnote bottom-left: "Fuente: BCRP"
period: 2018Q1:end
series:
  - {name: Consumo,     data: "excel:pbi.xlsx#trim!c_consumo",   type: stacked}
  - {name: Inversión,   data: "excel:pbi.xlsx#trim!c_inversion", type: stacked}
  - {name: Sector ext., data: "excel:pbi.xlsx#trim!c_xn",        type: stacked}
  - {name: PBI,         data: "excel:pbi.xlsx#trim!pbi_yoy",     type: line, mark: last}
annotations:
  - hline: 0
```

## Data resolution
Ref grammar dispatched by prefix: `excel:<file>#<sheet>!<column>` (implemented); `gsheet:`/`db:` recognized, not implemented. Inline data: a list (aligns positionally to the `period` window) or a `{period: value}` map. The resolver contract is fixed: **always** a tidy/long DataFrame `[period, series, value]`, normalized wide→long once at the boundary. Workbook paths resolve against `data_root` (env `ECONCHARTS_DATA_ROOT`; the CLI sets it to the spec/batch file's directory). Excel period column defaults to the sheet's first column; freq is inferred (string tokens, bare years, or datetimes via median spacing).

## Time & framing
- Internal index = pandas Periods with explicit freq (D/Q/M/Y), one freq per chart.
- `period` is the **authoritative axis frame**: the chart spans exactly that window (xlim + ticks) even where a series has no data; data outside is clipped; no `period` → the data's own range. Either bound may be the data-driven token `start`/`end` (sample min/max across all dated series — ≠ any one series' own first/last, which is what `mark: last` means). `end` forces the two-phase resolve in `render._resolve_framed`.
- **Every date→axis-x conversion goes through `render._periods_to_x` and friends** — periods map to their *midpoint*; bars/vlines use period *boundaries* (see `AxisCoords`). Never mix strings / Timestamps / mpl-dates downstream.
- `timeaxis.plan_ticks` picks the display granularity adaptively (finest that fits the width; thin every-other before coarsening) — daily data over a decade labels in years.
- es-PE formatting (month abbrevs, `,` decimal / `.` thousands) lives in `theme.py` — never in the spec.

## Theme
- **Which keys belong in a theme, and which in code.** If the HOST already names it — stroke weights, type sizes, gridline colour — say it in the host's own language (`rc:` here, a `format.series:`/`format.axis:` tree in the Excel edition); a third name buys nothing. If only **econcharts** names it — mark placement, deck furniture, named physical sizes, tick planning — use ONE name in both editions, because there the alternative is inventing the same concept twice. Every key the two themes already share is of the second kind. `Theme.val("format.marks.spread_gap", default)` reads them; typed fields remain the interface for the long-standing keys.
- **A theme carries preferences, not invariants.** The test: *would a different value give a different house style, or broken output?* The label-overlap floor (pitch ≥ one text height) and `PERP_SLOPE_THRESHOLD` (~17°) are geometry and live in code; `spread_gap`, `perp_gap` and `leader_after_pitches` are house style and live in `format.marks`.
- A theme = one `themes/<name>.yaml` (single source of truth): named `colors` table, series `cycle`, `annotations` vocabulary, `date_labels` patterns, matplotlib `rc` params. `theme.py` is the generic engine — it resolves color NAMES→hex everywhere and applies rc in memory (no `.mplstyle` on disk).
- **Never hard-code a color in renderers** — pull from the active theme.
- `bbva` is the reference theme; primary `#001391`, extracted from the official `Addin_BBVA_2025.xlam` (May 2025, "Version 3").
- **Type and stroke follow the TARGET, not one global value** (`size_styles.<size>`, applied by `Theme.rc_for`). The presets are four destinations, not four scalings of one chart: a Word figure is read at arm's length at 1:1, a slide is projected and read from metres away, so it needs BIGGER absolute type and a thicker stroke even though the figure is larger — 7pt/2pt for the Word presets, 10pt/3pt for the slide ones, as the add-in's `LetFontSizeAxes`/`LetLineSizeAxesMarker` do. The title is deliberately not in that table. Nothing scales on its own (figure in mm, type in pt, both absolute), so larger type buys its room from the plot area.
- Anything that ESTIMATES from a font size must read the live one: `_legend_columns` assumed 8pt while the legend was set at 10 and let a three-entry row run off the figure. `timeaxis.max_labels_for`'s labels-per-inch is calibrated at the base size and is conservative enough at 10pt (measured across the gallery: no date labels overlap).
- **Named output sizes** (the add-in's export presets, physical mm): `word_half` 75×60, `word_full` 117×60, `slides_half` 85×70 (**default — use this when showing examples**), `slides_full` 140×75. Size and backend are render-time choices (one spec → many targets), not spec fields.

## Marks & label placement
matplotlib's weak spot is label collision; econcharts handles it **deterministically** (no adjustText — it was dropped):
- **`charttypes.CHART_TYPES` is the single per-type dispatch point**: each strategy class owns its drawing (stacking/dodging via the shared `GroupState`), its typed geometry (`BarGeom`/`AreaGeom`/`StackedGeom`), and its mark placement — adding a chart type (e.g. `fan`) is one new class, not parallel switches across modules.
- Placement primitives in `marks.py`: line → dot + label on the outer side of the curve; bar → above (below if negative); area → above the curve; stacked → centered in the segment with auto white/navy contrast.
- Cross-series rules in `draw_line_marks`: at a shared x the lowest goes below, rest above; 3+ series at the last point go right of the endpoint. **Exception at the last point**, where a line has only ONE neighbour and the incoming stroke occupies the side it descends from: with exactly two marks there, `marks.flip_end_label_onto_clear_side` drops the upper label below when its own line falls into the point — judged geometrically (`intrusion = fall x min(1, halfLabelWidth / distance to the neighbour)`), and refused when the two endpoints are closer than a label pitch. **A LONE mark's window is its own label, not its two neighbours** (`marks.clear_lone_marks`): on a dense chart the label is wider than the gap between points, so the pair that chose its side says nothing about what it has to clear — an 86-point series in an 85mm panel gives ~2.3pt per point against a ~28pt label. It re-picks the side by which one the curve intrudes into less across the label's width, and places it past the curve's excursion there rather than a fixed gap from the point; it then retires the `PerpSpec` so the perpendicular pass skips it. The density gate needs no constant — if no other point falls under the label there is nothing to weigh and the existing answer stands, which is every sparse chart. It applies at the LAST point too: the endpoint rules all want two marks or more, so a single-series chart's final label is otherwise unowned. Found in the Excel edition against real decks, not by the suite — `tests/test_marks_dense.py` is the fixture the suite lacked. Each value axis is drawn and finalized on its OWN `placed` list, which is blind across axes, so `marks.decollide_across_axes` runs last and separates end labels belonging to different axes — only when they actually overlap. **The endpoint rule is a mirror pair and is one function** (`_end_stroke_intrudes`): the upper label of a series FALLING into its last point, and the lower label of one RISING into it. Once the sign is factored out the geometry is identical; the Excel edition met these as two rules months apart before seeing they were the same one. A series cannot do both, but both move into the same gap between the two endpoints, so only one runs. **A label may also not sit on ANOTHER label of the same line** (`marks.decollide_neighbour_marks`): every other rule here concerns a label and the curve, and nothing else in the suite would see a label on its neighbour. It reflects the later annotation's offset through its own point — cheaper than re-placing, and checked rather than trusted: the flip is kept only if the result is clear of EVERY other label of that series, since checking only the pair is how moving one label off its neighbour lands it on a third. It fires rarely, and the shape that needs it is specific — on a wandering curve two nearby marks get different windows and `clear_lone_marks` separates them for free; it takes a FLAT stretch with equal values (the real deck's two labels both reading `34.8`) for both windows to come out symmetric, both labels to go above, and land on each other. `PlacedMark.series_key` exists only so this rule can ask "same line?" of a flat list.
- `render._finalize_marks` post-processes after layout: hides stacked labels that don't fit their segment, offsets line labels perpendicular to the local slope (constant visual gap), separates cramped right-labels **isotonically** (`marks.separate`, pool-adjacent-violators: only runs that actually collide are pooled, each centred on its own mean, so an uncrowded label keeps its own height), draws a leader only for a label that travelled at least `marks.LEADER_AFTER_PITCHES` of a label height, then grows axis limits (capped) so nothing clips.
- Placement appends one `marks.PlacedMark` record per artist (with optional `SegmentFit`/`PerpSpec`/right-anchor) to a list render threads through — the **explicit contract** `_finalize_marks` iterates (no artist scanning or attribute smuggling). Mark artists are `set_in_layout(False)` so constrained layout ignores them.

## Renderer & output
- One `render(spec, size) -> Figure`; `save(fig, out, backend)` infers the backend from the suffix. **No `bbox_inches="tight"`** — the figure must save at its exact named physical size; constrained layout fits content *within* the fixed figsize instead.
- `png` (Google Slides): dpi=300, transparent. `svg`/`pdf` are registered but unpolished (svg still needs `svg.fonttype: "none"` for LaTeX text matching).
- Annotation mapping: `span`→`axvspan`, `band`→`axhspan` (label auto-placed in the widest clear stretch), `vline`→`axvline`, `hline`→`axhline`.
- Layering: fills behind bars behind lines (`Z_AREA < Z_BAR < Z_LINE`), annotation fills below / vlines above series, labels on top.

## Batch & deck & CLI
- A batch = orchestration header (`data_root`, `output_dir`, `render` subset) + inheritable defaults (`theme`, `size`, `backend`, `date_label`: header → chart override) + `charts` keyed by `id`. Header validated up front; chart bodies validated lazily so one bad chart can't sink the batch (**fail-soft** — `run_jobs` records per-chart errors and continues). Paths resolve relative to the batch file. Outputs `<id>_<yyyymmdd>.<backend>`.
- **`chrome` decides where a chart's words go, and it is a property of the SIZE preset, not a spec key** (`size_styles.<size>.chrome`). `chart` — the four original presets — draws title, units line and source inside the figure and the deck is a plain sheet of figures at true physical size. `slide` — the two 16:9 presets — renders the chart **bare** and `deck.py` sets its caption above a rule on a white panel, over a light-grey canvas, with a title placeholder, the source as a footnote and a page number. That is how BBVA decks are actually built (every chart measured in *Sistema Bancario* has no title of its own). The same YAML renders either way; only the surface the words land on moves.
- The furniture is **drawn, not inherited from a .pptx** — the BBVA template is an asset this repo does not carry — so every number lives in the theme under `deck.slide`, in millimetres, measured off real slides. A long caption **shrinks** to `caption.min_size` rather than moving the rule, whose distance below the panel top is the house style. matplotlib measures text; python-pptx cannot, so the fit is estimated from character count (the Excel edition asks PowerPoint directly).
- `econcharts build batch.yaml [--only ids] [-o DIR] [--force]` renders all + assembles a PPTX deck via `deck.py`; asks once before overwriting. `econcharts render spec.yaml -o out.png [--size] [--backend]` is the single-chart shortcut. Non-zero exit if anything failed.

## Ship (frozen exe)
`ship/econcharts.spec` is the checked-in PyInstaller manifest (bundles `themes/`, pptx templates; excludes GUI toolkits); `ship/build.py` freezes, lays user-facing files (examples, manual.html, run.bat) at the bundle root, and zips to `~/econcharts_ship.zip`. Build from the project `.venv` (clean python.org Python — not Anaconda).

## Conventions
- Python ≥3.11 (dev env: project `.venv`, Python 3.14, mpl 3.11 — install with `pip install -e ".[dev]"`); pydantic v2; matplotlib only for rendering; Agg backend in tests.
- **Errors surface at the right boundary naming the offending key — never a raw matplotlib/pandas traceback.** Spec problems → `SpecError`; data → `DataError`; theme → `ThemeError`; render → `RenderError`; batch header → `BatchError`.
- One responsibility per module, per the layout above. `timeaxis` stays pure (no drawing).
- themes/ and registry/ are data OUTSIDE the package, resolved relative to `econcharts/` — works for editable installs and the frozen exe (`--add-data`); a plain wheel would not see them, and wheels are a non-goal.
- No browser/interactive output; no AI in the render path.

## Testing
- `pytest` from the project `.venv` (~290 tests). Golden images per chart type in `tests/baseline/` via `pytest-mpl` (`pytest --mpl`). Schema tests assert malformed specs fail at the right key.
- **`tests/test_label_overlap.py` asserts that no mark label sits on another**, over every example spec at three named sizes. That question had never been asked: every other check is about a label and the *curve*, or about structure and counts, and the golden images sat stale for months without anyone noticing — a stale baseline cannot report a collision anyway. The Excel edition added the same check and it found eight overlapping pairs immediately, on charts that had been looked at all day. Python comes out at **zero**, so it is a hard assertion rather than the budget that edition needs, and staying at zero is the thing worth defending.
- `conftest.py` at the repo root sets Agg + points `ECONCHARTS_DATA_ROOT` at `examples/`.

## Dependencies
Core: `matplotlib, pandas, numpy, scipy` (PCHIP smoothing only), `pydantic>=2, pyyaml, openpyxl, python-pptx`. (`adjustText` is listed in pyproject but unused — placement is deterministic; drop it when touching deps.) Later resolvers: `gspread, google-api-python-client, requests`.

## Non-goals
- Not a general grammar of graphics (not ggplot / Vega). Not interactive / web.
- No per-chart styling beyond theme-named selections + the `style:` escape hatch.
- No AI in the render path. No wheel distribution (the ship is a frozen exe).

# econcharts — CLAUDE.md

## Purpose
Publication-quality economic charts from a minimal spec. The author supplies
content, data, a chart type per series and domain annotations; every formal
choice (colour, type, layout) is pre-encoded in a theme. A narrow DSL for macro
time series — deliberately not a general grammar of graphics.

## The organising idea: LaTeX for charts
The spec is the `.tex`, the theme is the `.sty`, `GRAMMAR.md` is the language
reference. It is WYSIWYM: the author says what something means and the system
decides how it looks — `period` frames the axis instead of the author setting
limits, `mark: last` instead of placing a text box, `chrome` follows the output
size instead of the spec.

The project grows along one axis: **more meaning, not more form knobs.** New
vocabulary that lets an economist say something they previously had to
hand-compute or hand-place is the point. A raw formatting option is drift;
`style:` exists as the escape hatch (`\vspace{}`), and reaching for it is a
smell. The test for any proposed key: *does it let the author say something
they mean, or only something they want it to look like?* (`transform: yoy`
passes; `linewidth: 2.5` does not.)

## Principles
- **Spec, not code.** YAML, validated and resolved by deterministic Python,
  rendered by a fixed engine. No AI in the render path.
- **Substance over form.** Overrides are selections from theme-named sets
  (`color: orange`, `line: dashed`), never raw values. `style:` is the one
  raw-value escape hatch.
- **Hand-authorable first.** An AI authoring layer, if ever, is separate and
  built last.
- **Out of scope for now (2026-09-19):** the domain registry (`recessions:
  peru`, `target: inflation_pe`). On-strategy but not next — `registry/` stays
  empty and `tests/test_spec.py` keeps asserting `recessions:` is refused. Don't
  start it unprompted.

## Working here

```
pytest                                   # the suite
pytest --mpl                             # + golden images (tests/test_render.py)
pip install -e . --no-build-isolation    # reinstall after a version bump
econcharts build examples/gallery.yaml --force   # -> examples/_gallery/ (gitignored)
econcharts render spec.yaml -o out.png [--size S] [--backend svg|pdf]
python ship/build.py                     # frozen exe -> ~/econcharts_ship.zip (last built 2026-06-16)
```

Use the project `.venv` (python.org Python 3.14, not Anaconda); first install
is `pip install -e ".[dev]"`. Reinstall only when the version changes —
`tests/test_version.py` catches stale metadata. **Always pass
`--no-build-isolation`**: the default build isolation took 85 s and made the
machine unresponsive (measured), because it builds a throwaway venv inside a
OneDrive folder; without it the reinstall takes ~2 s.

**Look at the output.** Render into the workspace — `examples/_gallery/`, or
the Excel repo's gitignored `work/` — never a temp dir the user cannot open, and
at `slides_half` unless asked otherwise. Structural tests and golden images
cannot see most visual defects: the fan golden image (tolerance 20) passed a
two-thirds alpha change at RMS 5.38 and band smoothing at RMS 0.68. When a
change affects appearance, read the PNG, and where a property can be asserted
geometrically (vertex counts, label boxes, axis limits), assert that instead.

Versioning: bump `pyproject.toml` with each shipped change — patch for fixes,
minor for new spec surface.

## Environment gotchas (Windows)
- The repo lives under OneDrive, so every write is synced. Heavy regenerable
  output (`.venv`, `ship/dist`, `ship/build`) is gitignored but still synced;
  moving the working copy out of OneDrive is on the notes repo's `roadmap.md`
  §3. An Excel/matplotlib export can occasionally land as a 0-byte file while
  OneDrive holds it — re-run before concluding anything.
- Working tree is **CRLF** (`.gitattributes`: LF in the repo, CRLF checked
  out). An exact-string edit built with `\n` matches nothing in a CRLF file;
  detect the file's convention first.
- Write multi-line patches as script **files**, not inline `python -c`/heredoc
  strings. Backticks inside a double-quoted shell string are command
  substitution — once that ran `pip install` against the system Python — and
  `\b`/`\x00` in heredocs have been mangled into literal bytes.
- The console is cp1252: printing `≥`, `—` etc. from Python raises
  `UnicodeEncodeError` even when the file write succeeded.
- `importlib.metadata.version("econcharts")` run from the repo root is
  shadowed by the gitignored `econcharts.egg-info/`; check installs from
  another cwd.

## Two editions
`econcharts_excel/` is the VBA add-in edition: a separate git repo with its own
remote, nested here and gitignored by this one. It is in scope from this
session; its commits go to its own remote, never into this repo.

**Read `econcharts_excel/CLAUDE.md` before working there.** A CLAUDE.md in a
subfolder is not loaded when a session starts here, only once files inside it
are read — so its rules (Office safety, VBA traps, build and check commands)
are not in effect until you open it. It is the authority for that edition;
this file deliberately doesn't repeat it, so the two can't drift apart.

Shared between the editions: `GRAMMAR.md` (here) is the grammar for both, and
keys only econcharts names — mark placement, deck furniture, sizes, fan
strengths — use one name in both themes.

## Architecture
`YAML → spec.py (pydantic, validate) → data.py (resolve to long df) +
render._resolve_framed (frame) → matplotlib → png | svg | pdf`; at batch level
`batch.yaml → per-chart jobs (fail-soft) → figures + .pptx deck`.

```
econcharts/
  spec.py        pydantic v2 models, YAML load + validation (the spec boundary)
  data.py        DataResolver; ref grammar; period parsing; long-df contract
  charttypes.py  CHART_TYPES strategy classes; PCHIP smoothing primitives
  marks.py       value-label placement primitives + cross-series rules
  annotations.py hline / vline / span / band
  timeaxis.py    adaptive date-axis tick planning (pure, no drawing)
  theme.py       theme engine: loads themes/*.yaml, es-PE formatters, sizes
  render.py      spec -> Figure; framing; mark finalization; save
  batch.py       batch documents: header cascade, fail-soft run
  deck.py        PNGs -> .pptx (plain sheet or the BBVA slide)
  cli.py         `econcharts build` / `econcharts render`
  errors.py      the error hierarchy
themes/bbva.yaml the house style — single source of truth for all form
registry/        empty (see Principles)
examples/        generic specs, datos.xlsx, gallery.yaml
tests/           pytest; golden images in tests/baseline/
ship/            PyInstaller manifest + build script
```
`bbva source/` holds the original add-in and reference decks — never commit it.
Worked examples built from real figures go in gitignored `work/` folders, not
`examples/`, which holds generic fixtures only.

Contracts that everything else relies on:
- **Resolver output is always a long DataFrame `[period, series, value]`**,
  normalized once at the boundary.
- **`charttypes.CHART_TYPES` is the single per-type dispatch point.** Each class
  owns its drawing, its typed geometry (`BarGeom`/`AreaGeom`/`StackedGeom`) and
  its mark placement; stacking and dodging go through the shared `GroupState`.
  A new chart type is one new class, not parallel switches. `draw()` takes a `bands=None` carrier so the
  draw loop never asks what type it holds.
- **Mark placement records one `marks.PlacedMark` per label** (with optional
  `SegmentFit` / `PerpSpec` / right-anchor) into a list that
  `render._finalize_marks` iterates — no artist scanning. Mark artists are
  `set_in_layout(False)`.
- **Every date→x conversion goes through `render._periods_to_x` and friends**:
  periods map to their midpoint; bars and vlines use period boundaries
  (`AxisCoords`).
- **Errors surface at the boundary that owns them, naming the key** — never a
  raw matplotlib/pandas traceback: `SpecError`, `DataError`, `ThemeError`,
  `RenderError`, `BatchError`.
- `themes/` and `registry/` are data outside the package, resolved relative to
  `econcharts/`. That works for editable installs and the frozen exe; a wheel
  would not see them, and wheels are a non-goal.

## Design rationale

### The spec
`GRAMMAR.md` is canonical and frozen — read it before writing or judging a
spec, update it in the same change as any spec-surface change, and don't copy
it here. Two things worth knowing: `type` is per series and is also the
combination rule (bars dodge, `stacked` stacks ±, areas fill and stack, lines
on top), and `mark` is a per-series field, not an annotation.

### Data
Refs dispatch by prefix: `excel:<file>#<sheet>!<column>` is implemented;
`gsheet:`/`db:` are recognized and refused. Inline data is a list (aligned to
the `period` window) or a `{period: value}` map. Workbook paths resolve against
`data_root` (env `ECONCHARTS_DATA_ROOT`; the CLI sets it to the spec's folder).
Frequency is inferred once per chart.

### Time and framing
- Internally pandas Periods, one frequency per chart.
- `period` is the authoritative frame: the axis spans exactly that window even
  where data is missing, and data outside is clipped. Either bound may be
  `start`/`end` (min/max across all dated series — not any one series' own
  last point, which is what `mark: last` means); `end` forces the two-phase
  resolve in `render._resolve_framed`.
- `timeaxis.plan_ticks` picks the finest granularity that fits, thinning
  every-other before coarsening. `timeaxis.max_labels_for` is calibrated at the
  base font size and measured conservative at 10pt.
- es-PE formatting lives in `theme.py`, never in the spec.

### Theme
- One `themes/<name>.yaml`: colour table, series `cycle`, annotation vocabulary,
  date label patterns, matplotlib `rc`. `theme.py` resolves colour names and
  applies rc in memory. Never hard-code a colour in a renderer.
- **Preferences in the theme, invariants in code.** Ask: would a different
  value give a different house style, or broken output? House style
  (`format.marks.spread_gap`, `perp_gap`, `leader_after_pitches`, fan
  strengths) is read with `Theme.val(...)`; geometry (the label-overlap floor,
  `PERP_SLOPE_THRESHOLD`) stays in code.
- If the host already names a setting (stroke weight, type size, gridline
  colour), use the host's name (`rc:`); if only econcharts names it, use one
  name in both editions.
- `bbva` is the reference theme; primary `#001391`, from the official
  `Addin_BBVA_2025.xlam`.

### Sizes and chrome
Named physical sizes in mm (w × h), the add-in's export presets:
`word_half` 75×60, `word_full` 117×60, `slides_half` 85×70 (default),
`slides_full` 140×75, `slides16_9_half` 100×80, `slides16_9_full` 218×80. Size
and backend are render-time choices, not spec fields.
- Type and stroke follow the *destination*, not a scale factor
  (`size_styles.<size>`, applied by `Theme.rc_for`): 7pt/2pt for Word, 10pt/3pt
  for slides — a projected slide needs bigger absolute type. Nothing scales on
  its own; larger type takes its room from the plot.
- Anything estimated from a font size must read the live size
  (`_legend_columns` is passed `_legend_fontsize()` for this reason).
- `chrome` is a property of the size preset. `chart` (the four original sizes)
  draws title, subtitle and source inside the figure. `slide` (the two 16:9
  sizes, which match real deck charts at ~100×80) renders the chart bare and
  `deck.py` sets the words on the slide — how BBVA decks are actually built.

### Marks and label placement
Placement is deterministic (no adjustText). Primitives in `marks.py`: line →
dot plus label on the outer side of the curve; bar → above (below if negative);
area → above the curve; stacked → centred in the segment with contrast colour.

Cross-series rules, applied in this order in `draw_line_marks` and
`_finalize_marks`:
1. At a shared x the lowest label goes below, the rest above; three or more at
   the last point go to the right of the endpoint.
2. **Endpoint pair** (`flip_end_label_onto_clear_side`, one mirror-symmetric
   rule in `_end_stroke_intrudes`): with exactly two marks at the last point,
   a label moves to the other side when its own line arrives from that side —
   judged geometrically, refused when the endpoints are closer than a label
   pitch.
3. **Lone marks** (`clear_lone_marks`): on dense charts a label is wider than
   the gap between points, so its side is chosen by which side the curve
   intrudes on less across the label's own width, placed past the excursion.
   No constant gates it — on sparse charts nothing falls under the label and
   the earlier answer stands. Applies at the last point too.
   `tests/test_marks_dense.py` is its fixture.
4. **Same-line neighbours** (`decollide_neighbour_marks`): a label may not sit
   on another label of the same series; the later one is reflected through its
   point, kept only if clear of every other label of that series. Needs a flat
   stretch of equal values to fire. `PlacedMark.series_key` exists for this.
5. Stacked labels that don't fit their segment are hidden; line labels get a
   perpendicular offset along the local slope; isotonic separation of cramped
   right-labels (`marks.separate`, pool-adjacent-violators); a leader only for
   a label moved at least `leader_after_pitches` label heights; then axis
   limits grow (capped) so nothing clips.
6. Each value axis is finalized on its own `placed` list, so
   `decollide_across_axes` runs last to separate end labels from different
   axes when they actually overlap.

### Fan charts
A fan is a central path plus nested intervals: one line and N fills. The
grammar (`intervals`, `conf`, `shade`, `shade_strength`) is in `GRAMMAR.md`;
the implementation facts that aren't:
- Fills are drawn by `FanType` itself with `fill_between`, not through
  `AreaType` (which stacks on `GroupState.area_cum`), at `Z_FAN`, below
  everything.
- **Bands are non-overlapping rings**, each filled only between itself and the
  next one in, so each composites at exactly its named alpha. The ramp runs
  `soft` (outermost) → `strong` (innermost), interpolated for any count, with
  `medium` as the midpoint. Rings are also what the Excel edition's stacked
  areas consume.
- Every ring edge is PCHIP-smoothed on a shared grid (`_smooth_ring`),
  restricted to the span where both edges are finite — `_smooth_onto` bridges
  NaNs and would otherwise extrapolate a band back over history.
- Fills open from the last period with no interval, where `lo` and `hi`
  collapse onto the path. Intervals sort widest-first by `conf`, and nesting is
  checked against the data.
- Interval refs resolve under synthetic names (`charttypes.fan_band_name`) so
  they obey the long-df contract and are framed and clipped like any series.
- Marks are not fan-aware: the central path joins the ordinary line-mark
  pipeline and sees only its own `y`.
- The visibility floor for `soft` was set with **CIEDE2000** against white
  (0.25 puts `lightblue` at ΔE00 > 5, "clearly visible").

### Output and deck
- `render(spec, size) -> Figure`; `save()` infers the backend from the suffix.
  No `bbox_inches="tight"` — the figure must keep its exact physical size;
  constrained layout fits content inside it.
- PNG at 300 dpi, transparent. SVG keeps text as text (`svg.fonttype: none`),
  PDF embeds fonts (`pdf.fonttype: 42`), both via `_BACKEND_RC` inside an
  `rc_context` so settings don't leak across a batch.
- Layering: `Z_FAN < Z_AREA < Z_BAR < Z_LINE`; annotation fills below series,
  vlines above, labels on top.
- Annotations: `hline`→`axhline`, `vline`→`axvline`, `span`→`axvspan`,
  `band`→`axhspan` with its label placed in the widest clear stretch.
- A batch is an orchestration header (`data_root`, `output_dir`, `render`)
  plus inheritable defaults (`theme`, `size`, `backend`, `date_label`) plus
  `charts` keyed by `id`. The header is validated up front; chart bodies
  lazily, so one bad chart doesn't sink the batch (`run_jobs` records per-chart
  errors and carries on). Outputs are `<id>_<yyyymmdd>.<backend>`.
  `econcharts build` takes `--only ids`, `-o DIR` and `--force` (it otherwise
  asks once before overwriting) and exits non-zero if anything failed.
- Slide furniture is drawn, not inherited from a .pptx: every number lives in
  the theme under `deck.slide`, in mm measured off real slides. A long caption
  shrinks to `caption.min_size` rather than moving the rule. python-pptx can't
  measure text, so fit is estimated from character count.

## Rejected approaches (don't retry)
- **WCAG 1.4.11 as a visibility test** — an accessibility floor, not a
  visibility one: nine of twelve house colours fail it as solid marks, and no
  alpha brings a pale fill to 3:1.
- **CIE76 for colour difference** — overstates blue differences ~2.7×, and
  every shade colour here is blue. Use CIEDE2000.
- **The gridline as a visibility anchor** — a 0.5 pt hairline needs far more
  contrast than a filled area.
- **Nested full fills for fan bands** — alphas compound, so the visible shade
  depends on the interval count and three strong bands go opaque.
- **adjustText** — replaced by deterministic placement.
- **`bbox_inches="tight"`** — breaks the exact physical size.

## Testing
- Golden images live in `tests/baseline/` (`pytest --mpl`). Their tolerance is
  loose, so treat them as a check on layout and draw order, not on colour or
  shading.
- `tests/test_label_overlap.py` asserts that **no mark label overlaps another**
  across every example spec at three sizes. Python is at zero, so it is a hard
  assertion — keep it at zero. (The Excel edition runs the same check against a
  budget.)
- Schema tests assert that malformed specs fail at the right key.
- `conftest.py` sets Agg and points `ECONCHARTS_DATA_ROOT` at `examples/`.

## Backlog
Direction is a richer spec language; candidates are weighed by how much meaning
they add. Nothing is scheduled — build when asked.
- Language: port categorical charts to Python; a semantic transform layer
  (`yoy`, `index`, `contribution`); spec reuse (LaTeX's `\newcommand`/`\input`
  — today only the batch header cascade reuses anything); facets.
- Infrastructure: gsheet/db resolvers (db = tsdb-api at `db.simgol.net`); drop
  scipy (used only for `PchipInterpolator`; ~166 MB across `.venv` and the
  frozen bundle); move the working copy out of OneDrive and have builds clean
  up after themselves (notes repo `roadmap.md` §3).
- AI authoring layer: last.

## Dependencies
`matplotlib, pandas, numpy, scipy` (PCHIP only), `pydantic>=2, pyyaml,
openpyxl, python-pptx`. Dev extras: `pytest, pytest-mpl, pyinstaller`.

## Non-goals
Not a general grammar of graphics. No interactive or web output. No per-chart
styling beyond theme selections and `style:`. No AI in the render path. No
wheel distribution — the ship is a frozen exe.

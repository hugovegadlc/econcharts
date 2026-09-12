# econcharts

Publication-quality economic charts from a minimal, substance-only YAML spec. You
write the **content** — title, data, per-series chart type, domain annotations — and
then any particular style can be pre-encoded, so every chart comes out consistent. A narrow DSL
for macro time-series charts, deliberately **not** a general grammar of graphics.

```yaml
charts:
  - id: inflacion
    title: Inflación — Perú
    subtitle: var. % anual del IPC
    period: 2021Q1:end
    series:
      - {name: Total,      type: line, data: "excel:datos.xlsx#inflacion!total"}
      - {name: Subyacente, type: line, data: "excel:datos.xlsx#inflacion!subyacente"}
    annotations:
      - {band: {y0: 1, y1: 3, label: Meta BCRP}}
```

## What it does

- **Spec, not code.** Charts are declared in YAML, validated by pydantic, and rendered
  by a fixed matplotlib engine. No plotting code, and no per-chart styling beyond
  selections from the theme's own vocabulary — with one raw-value escape hatch,
  the chart-level `style:` block.
- **Substance over form.** The spec carries content + domain semantics; all formal
  choices live in the theme. Overrides are *selections* from theme-named sets
  (`color: orange`, `line: dashed`), never raw values.
- **Time-series first.** Daily / monthly / quarterly / yearly data, with an adaptive
  date axis that picks the right label granularity for the span and width.
- **Authoritative framing.** `period` is the axis window (with `start`/`end` tokens
  that track the data); missing values leave clean gaps for forecast overlays.
- **Chart types.** `line` · `bar` · `area` · `stacked` (and combinations — e.g. stacked
  contributions with a total line).
- **Named output sizes.** Physical millimetres, not pixels: one spec renders to a
  Word column, a slide, or a full-width figure, and type and stroke follow the
  target rather than scaling with it.
- **Batches → decks.** One batch document renders many charts at once, each to its
  own figure, plus a PowerPoint deck. Two kinds: a plain sheet of figures at true
  export size, or — for the 16:9 presets — a built slide, where the chart renders
  bare and the deck sets its caption above a rule on a white panel, with the
  source as a footnote and a page number.
- **Ships to non-Python users.** A frozen executable + a `run.bat` runs the whole
  pipeline from a double-click — no install, no admin rights.

## Quickstart (developers)

Work in a per-project virtual environment (a clean, isolated box of just this
project's packages — not your global/Anaconda install):

```bash
py -3.14 -m venv .venv          # create the env (clean Python 3.14)
.venv\Scripts\activate          # use it (prompt shows (.venv))
pip install -e ".[dev]"         # econcharts + test/build tools, into the env only
```

> **Install it editable — `pip install git+https://…` will not work.** `themes/`
> and `registry/` are data that live *outside* the package, resolved relative to
> `econcharts/`. A wheel contains the package and nothing else, so a non-editable
> install imports fine and then fails on the first render with no theme to load.
> Wheel distribution is a deliberate non-goal; the artifact for non-developers is
> the frozen executable.

Then:

```bash
econcharts build examples/gallery.yaml      # → figures + gallery.pptx in examples/_gallery/
econcharts render examples/inflacion_pe.yaml -o chart.png
econcharts --version
pytest --mpl                                # run the test suite (with golden images)
```

## Documentation

- **[manual.html](https://hugovegadlc.github.io/econcharts/manual.html)** — the full user manual: quickstart,
  the spec reference, style vocabularies, batches & decks, and a worked gallery.
- **[GRAMMAR.md](GRAMMAR.md)** — the canonical spec grammar reference.
- **[CLAUDE.md](CLAUDE.md)** — design notes and project conventions.

## Pipeline

```
YAML spec → pydantic validate → resolve (data refs + frame) → matplotlib render → png | svg | pdf | pptx
```

| Module | Responsibility |
|--------|----------------|
| `spec.py` / `batch.py` | pydantic models, YAML load + validation |
| `data.py` | data resolution (Excel + inline), period parsing, the long-df contract |
| `charttypes.py` | per-series renderers (line / bar / area / stacked) |
| `annotations.py` | reference lines, bands, shaded spans |
| `marks.py` | per-series value labels + deterministic placement |
| `timeaxis.py` | adaptive date-axis granularity + tick planning |
| `theme.py` | the theme engine (loads `themes/*.yaml`), es-PE formatters |
| `errors.py` | the error vocabulary surfaced at each boundary |
| `render.py` | orchestration: spec → Figure → output backend |
| `deck.py` | assemble figures into a PowerPoint deck |
| `cli.py` | the `econcharts` command |

## Status

**v0.8.5** — the core pipeline is feature-complete and covered by `pytest` +
`pytest-mpl` golden images. Two themes: `bbva` (BBVA house style) and `macro`
(R/ggplot2 house style). SVG and PDF backends are complete — selectable text
(`svg.fonttype: none`), embedded fonts (`pdf.fonttype: 42`), transparent
backgrounds. `tick_rotation` for vertical x-axis labels (theme vocabulary, with a
per-chart override). Date-axis ticks anchor to the **last** available period,
which is the one a reader of a time series looks for first. MIT licensed. Ships
as a frozen Windows executable — no install, no admin rights.

Label placement is the part that took the most work, and it is entirely
deterministic (`adjustText` was tried and dropped). Labels are offset
perpendicular to the local slope, crowded end labels are separated isotonically
so an uncrowded one keeps its own height, a leader line is drawn only for a label
that actually travelled, and a dense chart re-picks each label's side by which
one its own curve intrudes into less across the label's width. A test asserts
that **no label sits on another** across every example at three sizes.

Backlog: domain registry (recessions / targets / event marks), Google Sheets & database
resolvers, `fan` chart type (forecast bands), slim bundle (drop scipy), and an optional
natural-language authoring layer.

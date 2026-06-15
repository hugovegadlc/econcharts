"""Render behavior + pytest-mpl golden images.

The behavioral tests assert the decisions we care about (smoothing, es-PE ticks,
bottom legend, palette colors, named sizes, no source line) without pixel
comparison, so they stay robust across machines. The mpl_image_compare tests
add true visual-regression coverage on top.
"""

from __future__ import annotations

import re

import pytest
from matplotlib.figure import Figure

from econcharts import render, save
from econcharts.render import RenderError
from econcharts.spec import Spec
from econcharts.theme import Theme, load_theme

_QLABEL = re.compile(r"^\dT\d{2}$")


def _legend_texts(fig):
    """Texts of the single combined figure legend (now a fig.legend, not ax)."""
    assert fig.legends, "expected a figure legend"
    return [t.get_text() for t in fig.legends[0].get_texts()]


def _labels(fig, minor=False):
    """Non-empty x tick labels of the primary axis."""
    return [t.get_text() for t in fig.axes[0].get_xticklabels(minor=minor) if t.get_text()]


def test_render_returns_figure(example_spec):
    assert isinstance(render(example_spec), Figure)


@pytest.mark.parametrize("size", list(load_theme("bbva").sizes_mm))
def test_render_applies_named_size(example_spec, size):
    fig = render(example_spec, size=size)
    assert tuple(fig.get_size_inches()) == pytest.approx(load_theme("bbva").figsize(size))


def test_default_size_is_slides_half(example_spec):
    fig = render(example_spec)
    assert tuple(fig.get_size_inches()) == pytest.approx(load_theme("bbva").figsize("slides_half"))


def test_no_title_lets_axes_fill_the_space():
    base = {"period": "2021Q1:2021Q4",
            "series": [{"name": "A", "type": "line", "data": [1, 2, 3, 4]}]}
    titled = render(Spec.from_dict({**base, "title": "T"}))
    untitled = render(Spec.from_dict(base))
    for f in (titled, untitled):
        f.canvas.draw()
    assert untitled.axes[0].get_title() == ""  # nothing drawn
    # axes top rises to reclaim the title's space
    assert untitled.axes[0].get_position().y1 > titled.axes[0].get_position().y1


def test_saved_size_is_exact_regardless_of_title_length(tmp_path):
    """A long title or legend must NOT widen the export (no bbox_inches='tight')."""
    from PIL import Image

    exp = (round(85 / 25.4 * 300), round(70 / 25.4 * 300))  # slides_half @300dpi
    sizes = set()
    for title in ("PBI", "Un título deliberadamente larguísimo " * 3):
        spec = Spec.from_dict({
            "title": title, "period": "2021Q1:2021Q4",
            "series": [{"name": "A", "type": "line", "data": [1, 2, 3, 4]},
                       {"name": "B", "type": "line", "data": [2, 3, 1, 4]}],
        })
        out = save(render(spec), tmp_path / "c.png")
        w, h = Image.open(out).size
        assert abs(w - exp[0]) <= 2 and abs(h - exp[1]) <= 2  # exact, both titles
        sizes.add((w, h))
    assert len(sizes) == 1  # identical size for short and long titles


def test_lines_are_smoothed(example_spec):
    fig = render(example_spec)
    ax = fig.axes[0]
    # 16 quarterly points in; a smoothed PCHIP curve has many more vertices.
    assert len(ax.get_lines()[0].get_xdata()) > 100


def test_first_series_uses_palette_primary(example_spec):
    fig = render(example_spec)
    assert fig.axes[0].get_lines()[0].get_color().lower() == "#001391"


def _two_lines(overrides):
    return Spec.from_dict({
        "title": "T", "period": "2021Q1:2021Q4",
        "series": [
            {"name": "A", "type": "line", "data": [1, 2, 3, 4]},
            {"name": "B", "type": "line", "data": [4, 3, 2, 1], **overrides},
        ],
    })


def test_line_style_override_makes_a_dashed_stroke():
    ax = render(_two_lines({"line": "dashed"})).axes[0]
    a, b = ax.get_lines()[:2]
    assert a.get_linestyle() == "-"    # default solid
    assert b.get_linestyle() == "--"   # dashed override


def test_named_color_override_pins_a_palette_color():
    from matplotlib.colors import to_hex

    ax = render(_two_lines({"color": "orange"})).axes[0]
    a, b = ax.get_lines()[:2]
    assert to_hex(a.get_color()).lower() == "#001391"   # palette cycle (unshifted)
    assert to_hex(b.get_color()).lower() == "#ffb56b"   # orange by name


def test_unknown_color_name_raises_render_error_naming_series():
    with pytest.raises(RenderError, match="B'.*unknown color 'chartreuse'"):
        render(_two_lines({"color": "chartreuse"}))


def test_line_style_on_non_line_series_rejected_at_spec_boundary():
    from econcharts.spec import SpecError

    with pytest.raises(SpecError, match="line.*only for line series"):
        Spec.from_dict({
            "title": "T", "period": "2021Q1:2021Q4",
            "series": [{"name": "A", "type": "bar", "data": [1, 2, 3, 4], "line": "dashed"}],
        })


def test_line_with_leading_trailing_nulls_starts_and_ends_at_real_data():
    # Missing values at the ends must not be bridged: the line spans only its first
    # to last real point. With data at indices 2..4 (2021Q3..2022Q1 of a Q1-Q4x2
    # window), the smoothed curve's x-range must stay within those period x-coords.
    from econcharts.render import _date_to_x

    spec = Spec.from_dict({
        "title": "T", "period": "2021Q1:2022Q4",
        "series": [{"name": "A", "type": "line",
                    "data": [None, None, 3.0, 4.0, 5.0, None, None, None]}],
    })
    line = render(spec).axes[0].get_lines()[0]
    xs = line.get_xdata()
    assert min(xs) == pytest.approx(_date_to_x("2021Q3"))   # first real point
    assert max(xs) == pytest.approx(_date_to_x("2022Q1"))   # last real point


def test_all_null_line_series_draws_nothing():
    spec = Spec.from_dict({
        "title": "T", "period": "2021Q1:2021Q4",
        "series": [{"name": "A", "type": "line", "data": [None, None, None, None]}],
    })
    assert render(spec).axes[0].get_lines() == []


def test_wider_window_frames_the_axis_beyond_the_data():
    # period: declares the x-extent; the axis spans it even where the series has no
    # data. Data covers 2022Q1..2022Q4, window is 2021Q1..2023Q4.
    from econcharts.render import _date_to_x

    spec = Spec.from_dict({
        "title": "T", "period": "2021Q1:2023Q4",
        "series": [{"name": "A", "type": "line",
                    "data": {"2022Q1": 1, "2022Q2": 2, "2022Q3": 3, "2022Q4": 4}}],
    })
    ax = render(spec).axes[0]
    x0, x1 = ax.get_xlim()
    assert x0 <= _date_to_x("2021Q1") and x1 >= _date_to_x("2023Q4")   # frame, not data


def test_end_token_frames_to_sample_max_not_series_last():
    # `end` resolves to the latest period across ALL series; `mark: last` still
    # points at the marked series' own last point. A ends 2022Q4, B ends 2023Q2.
    from econcharts.render import _date_to_x

    spec = Spec.from_dict({
        "title": "T", "period": "2022Q1:end",
        "series": [
            {"name": "A", "type": "line",
             "data": {"2022Q1": 1, "2022Q3": 2, "2022Q4": 3}, "mark": {"at": "last"}},
            {"name": "B", "type": "line", "data": {"2022Q2": 4, "2023Q2": 5}},
        ],
    })
    ax = render(spec).axes[0]
    assert ax.get_xlim()[1] >= _date_to_x("2023Q2")        # frame reaches sample end
    mark = [t for t in ax.texts if t.get_text() == "3"][0]  # A's `last` value label
    assert mark.xy[0] == pytest.approx(_date_to_x("2022Q4"))  # anchored at A's own last


def test_start_token_frames_to_sample_min():
    # `start` = the earliest period across all series (here B's 2021Q4), so the
    # frame's left edge tracks the data even though A starts later.
    from econcharts.render import _date_to_x

    spec = Spec.from_dict({
        "title": "T", "period": "start:2023Q1",
        "series": [
            {"name": "A", "type": "line", "data": {"2022Q2": 1, "2022Q3": 2}},
            {"name": "B", "type": "line", "data": {"2021Q4": 4, "2022Q1": 5}},
        ],
    })
    ax = render(spec).axes[0]
    assert ax.get_xlim()[0] <= _date_to_x("2021Q4")        # frame starts at sample min
    assert ax.get_xlim()[1] >= _date_to_x("2023Q1")        # explicit end honored


def test_line_ticks_point_at_data_points(example_spec):
    # A line chart's tick points AT a data point (major ticks); no separate boundary
    # marks (no minor ticks). Label *format* is adaptive, so not asserted here.
    fig = render(example_spec)
    labels = [t.get_text() for t in fig.axes[0].get_xticklabels() if t.get_text()]
    assert labels, "expected major (data-point) labels on a line chart"
    assert not any(t.get_text() for t in fig.axes[0].get_xticklabels(minor=True))


def test_date_labels_adapt_granularity_to_span():
    # 16 quarters over the default (narrow) width can't show every quarter -> the
    # axis coarsens to YEAR labels; a short 4-quarter span keeps quarter granularity
    # (month-style default: the quarter's closing month).
    wide = Spec.from_dict({"title": "T", "period": "2021Q1:2024Q4",
                           "series": [{"name": "A", "type": "line", "data": [1] * 16}]})
    assert _labels(render(wide)) == ["2021", "2022", "2023", "2024"]
    short = Spec.from_dict({"title": "T", "period": "2024Q1:2024Q4",
                            "series": [{"name": "A", "type": "line", "data": [1, 2, 3, 4]}]})
    assert _labels(render(short)) == ["mar-24", "jun-24", "set-24", "dic-24"]


def test_chart_date_label_override_selects_style():
    spec = Spec.from_dict({"title": "T", "period": "2024Q1:2024Q4", "date_label": "quarter",
                           "series": [{"name": "A", "type": "line", "data": [1, 2, 3, 4]}]})
    assert _labels(render(spec)) == ["1T24", "2T24", "3T24", "4T24"]


def test_unknown_date_label_raises():
    with pytest.raises(RenderError, match="unknown date_label"):
        render(Spec.from_dict({"title": "T", "period": "2024Q1:2024Q4", "date_label": "bogus",
                               "series": [{"name": "A", "type": "line", "data": [1, 2, 3, 4]}]}))


def test_bar_ticks_are_boundary_marks_with_centered_labels():
    # A bar chart puts MARKS on boundaries (major, unlabeled) and LABELS centered
    # under bars (minor).
    spec = Spec.from_dict(
        {"title": "T", "period": "2021Q1:2022Q4",
         "series": [{"name": "A", "type": "bar", "data": [1, 2, 3, 4, 5, 6, 7, 8]}]}
    )
    fig = render(spec)
    major = [t.get_text() for t in fig.axes[0].get_xticklabels()]
    assert not any(major)                     # boundaries unlabeled
    assert len(major) == 8 + 1                # a mark between/around all 8 bars
    assert _labels(fig, minor=True)           # centered labels exist (format adaptive)


def test_legend_lists_all_series(example_spec):
    fig = render(example_spec)
    assert _legend_texts(fig) == [s.name for s in example_spec.series]


def test_source_footnote_drawn():
    spec = Spec(**{
        "title": "Test",
        "source": "BCRP",
        "series": [{"name": "A", "type": "line", "data": [1, 2, 3]}],
        "period": "2024:2026",
    })
    fig = render(spec)
    texts = [t.get_text() for t in fig.texts]
    assert any("Fuente" in t and "BCRP" in t for t in texts)


def test_source_absent_no_footnote():
    spec = Spec(**{
        "title": "Test",
        "series": [{"name": "A", "type": "line", "data": [1, 2, 3]}],
        "period": "2024:2026",
    })
    fig = render(spec)
    texts = [t.get_text() for t in fig.texts]
    assert not any("Fuente" in t for t in texts)


# --- type-role layering: a line always sits above filled types, regardless of
#     the order series appear in the spec ---

def _combo_line_first(filled_type):
    """A spec with the LINE listed first, then a filled series of `filled_type`."""
    return Spec.from_dict({
        "title": "T", "period": "2021Q1:2021Q4",
        "series": [
            {"name": "Total", "type": "line", "data": [3, 3, 3, 3]},
            {"name": "Comp", "type": filled_type, "data": [1, 2, 3, 4]},
        ],
    })


@pytest.mark.parametrize("filled", ["bar", "stacked"])
def test_line_layers_above_bars(filled):
    ax = render(_combo_line_first(filled)).axes[0]
    line_z = max(l.get_zorder() for l in ax.lines)
    bar_z = max(p.get_zorder() for p in ax.patches)
    assert line_z > bar_z  # line on top even though it's first in the spec


def test_line_layers_above_area():
    ax = render(_combo_line_first("area")).axes[0]
    line_z = max(l.get_zorder() for l in ax.lines)
    area_z = max(c.get_zorder() for c in ax.collections)
    assert line_z > area_z


def test_contribution_combo_has_stack_and_total_line():
    from conftest import EXAMPLES

    ax = render(Spec.from_yaml(EXAMPLES / "pbi_contribuciones.yaml")).axes[0]
    assert len(ax.patches) == 24                 # 3 stacked components x 8 periods
    assert len([l for l in ax.lines if not l.get_label().startswith("_")]) == 1
    assert set(_legend_texts(ax.figure)) == {"PBI", "Consumo", "Inversión", "Sector externo"}


def _bar_with_annotations(annotations):
    return Spec.from_dict({
        "title": "T", "period": "2021Q1:2021Q4",
        "series": [{"name": "A", "type": "bar", "data": [1, -1, 2, -2]}],
        "annotations": annotations,
    })


def test_hline_draws_styled_reference_line():
    from matplotlib.colors import to_hex

    ax = render(_bar_with_annotations([{"hline": 0, "color": "orange",
                                        "weight": "thick", "line": "dotted"}])).axes[0]
    assert len(ax.lines) == 1  # bar chart has no series lines, so this is the hline
    ln = ax.lines[0]
    assert list(ln.get_ydata()) == [0, 0]
    assert to_hex(ln.get_color()).lower() == "#ffb56b"   # orange
    assert ln.get_linewidth() == 2.0                     # thick
    assert ln.get_linestyle() == ":"                     # dotted


def test_vline_sits_between_bars_on_bar_charts():
    from econcharts.render import _date_to_boundary

    ax = render(_bar_with_annotations([{"vline": "2021Q2"}])).axes[0]
    assert len(ax.lines) == 1
    xd = ax.lines[0].get_xdata()
    # on the period boundary (between bars), NOT the bar center
    assert xd[0] == xd[1] == pytest.approx(_date_to_boundary("2021Q2"))


def test_vline_sits_at_data_point_on_line_charts():
    from econcharts.render import _date_to_x

    spec = Spec.from_dict({
        "title": "T", "period": "2021Q1:2021Q4",
        "series": [{"name": "A", "type": "line", "data": [1, 2, 3, 4]}],
        "annotations": [{"vline": "2021Q2"}],
    })
    ax = render(spec).axes[0]
    vlines = [l for l in ax.lines if len(set(l.get_xdata())) == 1]  # vertical lines only
    assert len(vlines) == 1
    assert vlines[0].get_xdata()[0] == pytest.approx(_date_to_x("2021Q2"))  # at the midpoint


def test_hline_list_draws_one_line_each():
    ax = render(_bar_with_annotations([{"hline": [0, 1, 2]}])).axes[0]
    assert len(ax.lines) == 3


def _line_with_annotations(annotations):
    return Spec.from_dict({
        "title": "T", "period": "2021Q1:2021Q4",
        "series": [{"name": "A", "type": "line", "data": [1, 2, 3, 4]}],
        "annotations": annotations,
    })


def test_span_draws_shaded_region_between_boundaries():
    from matplotlib.colors import to_hex
    from econcharts.render import _date_to_boundary, _date_to_end

    ax = render(_line_with_annotations(
        [{"span": {"from": "2021Q1", "to": "2021Q2", "label": "X"}, "color": "orange"}])).axes[0]
    assert len(ax.patches) == 1                       # line chart -> only the span
    p = ax.patches[0]
    assert to_hex(p.get_facecolor()).lower() == "#ffb56b"   # orange fill
    assert p.get_alpha() == 0.25                            # theme alpha
    assert p.get_x() == pytest.approx(_date_to_boundary("2021Q1"))         # leading edge
    assert p.get_x() + p.get_width() == pytest.approx(_date_to_end("2021Q2"))  # trailing edge
    label = next(t for t in ax.texts if t.get_text() == "X")
    assert to_hex(label.get_color()).lower() == "#b98409"   # darker shade of orange


def test_band_draws_horizontal_region():
    from matplotlib.colors import to_hex

    ax = render(_line_with_annotations(
        [{"band": {"y0": 1, "y1": 3, "label": "Meta"}}])).axes[0]   # default grey
    assert len(ax.patches) == 1
    p = ax.patches[0]
    assert p.get_y() == pytest.approx(1)
    assert p.get_y() + p.get_height() == pytest.approx(3)
    assert to_hex(p.get_facecolor()).lower() == "#adb8c2"   # grey fill
    label = next(t for t in ax.texts if t.get_text() == "Meta")
    assert to_hex(label.get_color()).lower() == "#46536d"   # darker shade of grey


def test_band_label_placed_in_clear_gap():
    # line sits ABOVE the band everywhere -> band is empty -> label centred in it
    spec = Spec.from_dict({
        "title": "T", "period": "2021Q1:2022Q1",
        "series": [{"name": "A", "type": "line", "data": [5, 8, 8, 8, 5]}],
        "annotations": [{"band": {"y0": 1, "y1": 3, "label": "B"}}],
    })
    ax = render(spec).axes[0]
    label = next(t for t in ax.texts if t.get_text() == "B")
    x = label.get_position()[0]
    x0, x1 = ax.get_xlim()
    assert 0.3 < (x - x0) / (x1 - x0) < 0.7   # in the clear middle, not jammed at an edge
    assert label.get_ha() == "center"


def test_band_label_falls_back_when_no_clear_gap():
    # line stays INSIDE the band the whole time -> no gap -> top-right fallback
    spec = Spec.from_dict({
        "title": "T", "period": "2021Q1:2021Q3",
        "series": [{"name": "A", "type": "line", "data": [2, 2, 2]}],
        "annotations": [{"band": {"y0": 1, "y1": 3, "label": "B"}}],
    })
    ax = render(spec).axes[0]
    label = next(t for t in ax.texts if t.get_text() == "B")
    assert label.get_ha() == "right"   # fallback corner placement


def test_line_mark_draws_marker_and_value_label():
    from matplotlib.colors import to_hex

    spec = Spec.from_dict({
        "title": "T", "period": "2021Q1:2021Q4",
        "series": [{"name": "A", "type": "line", "data": [1, 2, 3, 4.5],
                    "mark": {"at": "last", "marker": True, "value": True}}],
    })
    ax = render(spec).axes[0]
    markers = [l for l in ax.lines if l.get_marker() == "o"]
    assert len(markers) == 1
    assert markers[0].get_ydata()[0] == pytest.approx(4.5)   # last point
    labels = [t for t in ax.texts]                            # no subtitle -> only the mark
    assert [t.get_text() for t in labels] == ["4,5"]          # value, es-PE
    assert to_hex(labels[0].get_color()).lower() == "#001391"  # series color


def test_line_mark_all_labels_every_point_no_marker():
    spec = Spec.from_dict({
        "title": "T", "period": "2021Q1:2021Q4",
        "series": [{"name": "A", "type": "line", "data": [1, 2, 3, 4],
                    "mark": {"at": "all", "value": True}}],
    })
    ax = render(spec).axes[0]
    assert [l for l in ax.lines if l.get_marker() == "o"] == []   # no dots
    assert sorted(t.get_text() for t in ax.texts) == ["1", "2", "3", "4"]


def test_line_marks_higher_value_above_lower_below():
    # two series marked at the same last point: higher value label above, lower below
    spec = Spec.from_dict({
        "title": "T", "period": "2021Q1:2021Q2",
        "series": [
            {"name": "Hi", "type": "line", "data": [1, 5], "mark": "last"},
            {"name": "Lo", "type": "line", "data": [1, 3], "mark": "last"},
        ],
    })
    ax = render(spec).axes[0]
    hi = next(t for t in ax.texts if t.get_text() == "5")
    lo = next(t for t in ax.texts if t.get_text() == "3")
    # labels are offset perpendicular to the slope; the y-component points up for
    # the higher value (above) and down for the lower (below).
    assert hi.xyann[1] > 0
    assert lo.xyann[1] < 0


def test_three_lines_last_point_labels_go_right():
    spec = Spec.from_dict({
        "title": "T", "period": "2021Q1:2021Q4",
        "series": [
            {"name": "A", "type": "line", "data": [1, 2, 3, 5], "mark": "last"},
            {"name": "B", "type": "line", "data": [1, 2, 3, 3], "mark": "last"},
            {"name": "C", "type": "line", "data": [1, 2, 3, 1], "mark": "last"},
        ],
    })
    fig = render(spec)
    ax = fig.axes[0]
    labels = [t for t in ax.texts]
    assert len(labels) == 3
    assert all(t.get_horizontalalignment() == "left" for t in labels)  # right of the points
    # the x-axis grew to make room beyond the last data point
    from econcharts.render import _date_to_x
    assert ax.get_xlim()[1] > _date_to_x("2021Q4")


def test_cramped_right_labels_get_leaders():
    # tall peak -> big y-range -> the near-identical endpoints are cramped in pixels
    spec = Spec.from_dict({
        "title": "T", "period": "2021Q1:2021Q4",
        "series": [
            {"name": "A", "type": "line", "data": [1, 8, 3, 2.1], "mark": "last"},
            {"name": "B", "type": "line", "data": [1, 7, 3, 2.0], "mark": "last"},
            {"name": "C", "type": "line", "data": [1, 6, 3, 1.9], "mark": "last"},
        ],
    })
    ax = render(spec).axes[0]
    leaders = [l for l in ax.lines if len(l.get_xdata()) == 2]   # 2-point leader segments
    assert len(leaders) == 3   # one per cramped right label


def test_single_line_min_below_max_above():
    # a V: the trough's label goes below, the (higher) endpoints above
    spec = Spec.from_dict({
        "title": "T", "period": "2021Q1:2021Q3",
        "series": [{"name": "A", "type": "line", "data": [3, 1, 3], "mark": "all"}],
    })
    ax = render(spec).axes[0]
    assert next(t for t in ax.texts if t.get_text() == "1").xyann[1] < 0   # trough -> below


def test_mark_decimals_consistent_across_axis():
    # two series sharing an axis; one last value needs a decimal -> BOTH get it
    spec = Spec.from_dict({
        "title": "T", "period": "2021Q1:2021Q2",
        "series": [
            {"name": "A", "type": "line", "data": [1.0, 2.0], "mark": "last"},
            {"name": "B", "type": "line", "data": [1.0, 2.4], "mark": "last"},
        ],
    })
    ax = render(spec).axes[0]
    assert sorted(t.get_text() for t in ax.texts) == ["2,0", "2,4"]   # not "2" and "2,4"


def test_dense_marks_do_not_collapse_the_axes():
    # `at: all` on a dense line must not let labels squish the plot (set_in_layout
    # keeps them out of layout; >8 labels skip adjustText and stay anchored).
    spec = Spec.from_dict({
        "title": "T", "period": "2021Q1:2024Q4",
        "series": [{"name": "A", "type": "line",
                    "data": [2, 3, 4, 5, 6, 7, 8, 8, 8, 7, 5, 3, 3, 3, 2, 2], "mark": "all"}],
    })
    fig = render(spec)
    fig.canvas.draw()
    assert fig.axes[0].get_position().width > 0.5   # axes keeps a sane width


def test_marks_expand_axis_to_avoid_clipping():
    base = {"title": "T", "period": "2021Q1:2021Q4",
            "series": [{"name": "A", "type": "line", "data": [1, 2, 3, 4]}]}
    no_mark = render(Spec.from_dict(base)).axes[0].get_xlim()[1]
    marked = base["series"][0] | {"mark": {"at": "last", "marker": True}}
    with_mark = render(Spec.from_dict({**base, "series": [marked]})).axes[0].get_xlim()[1]
    assert with_mark > no_mark   # right limit grew to fit the last-point dot/label


def test_mark_text_replaces_value():
    spec = Spec.from_dict({
        "title": "T", "period": "2021Q1:2021Q4",
        "series": [{"name": "A", "type": "line", "data": [1, 2, 3, 4],
                    "mark": {"at": "last", "text": "COVID-19"}}],
    })
    ax = render(spec).axes[0]
    assert [t.get_text() for t in ax.texts] == ["COVID-19"]


def test_bar_marks_above_positive_below_negative():
    spec = Spec.from_dict({
        "title": "T", "period": "2021Q1:2021Q2",
        "series": [{"name": "A", "type": "bar", "data": [2, -2], "mark": "all"}],
    })
    ax = render(spec).axes[0]
    va = {t.get_text(): t.get_verticalalignment() for t in ax.texts}
    assert va["2"] == "bottom"   # positive: label on top
    assert va["-2"] == "top"     # negative: label below


def test_stacked_marks_use_contrast_color():
    from matplotlib.colors import to_hex

    spec = Spec.from_dict({
        "title": "T", "period": "2021Q1",
        "series": [
            {"name": "Dark", "type": "stacked", "data": [3], "mark": "all"},   # #001391 dark -> white
            {"name": "Light", "type": "stacked", "data": [1], "mark": "all"},  # #85C8FF light -> navy
        ],
    })
    ax = render(spec).axes[0]
    color = {t.get_text(): to_hex(t.get_color()).lower() for t in ax.texts}
    assert color["3"] == "#ffffff"
    assert color["1"] == "#072146"


def test_stacked_mark_skips_segment_too_thin():
    spec = Spec.from_dict({
        "title": "T", "period": "2021Q1",
        "series": [
            {"name": "Big", "type": "stacked", "data": [5.0], "mark": "all"},
            {"name": "Sliver", "type": "stacked", "data": [0.02], "mark": "all"},
        ],
    })
    ax = render(spec).axes[0]
    visible = [t.get_text() for t in ax.texts if t.get_visible()]
    assert "5,00" in visible          # big segment labelled
    assert "0,02" not in visible      # sliver hidden (doesn't fit)


def test_area_marks_label_each_value():
    spec = Spec.from_dict({
        "title": "T", "period": "2021Q1:2021Q4",
        "series": [{"name": "A", "type": "area", "data": [1, 2, 3, 4], "mark": "all"}],
    })
    ax = render(spec).axes[0]
    assert sorted(t.get_text() for t in ax.texts) == ["1", "2", "3", "4"]


def _secondary_spec():
    return Spec.from_dict({
        "title": "T", "period": "2021Q1:2021Q4",
        "ylabel": "US$ bn", "y2label": "S/ por US$",
        "series": [
            {"name": "Reservas", "type": "line", "data": [70, 72, 74, 76]},
            {"name": "Tipo de cambio", "type": "line", "axis": "secondary",
             "data": [3.8, 3.75, 3.72, 3.78]},
        ],
    })


def test_all_primary_is_single_axis(example_spec):
    assert len(render(example_spec).axes) == 1


def test_secondary_axis_creates_independent_twin():
    fig = render(_secondary_spec())
    assert len(fig.axes) == 2
    prim, sec = fig.axes
    assert prim.get_ylim()[1] > 50    # reserves ~70s
    assert sec.get_ylim()[1] < 10     # exchange rate ~3.x — its own scale


def test_combined_legend_spans_both_axes():
    fig = render(_secondary_spec())
    assert sorted(_legend_texts(fig)) == ["Reservas", "Tipo de cambio"]


def test_y2label_on_secondary():
    assert render(_secondary_spec()).axes[1].get_ylabel() == "S/ por US$"


def test_secondary_axis_has_no_gridlines():
    sec = render(_secondary_spec()).axes[1]
    assert not any(gl.get_visible() for gl in sec.get_ygridlines())


def test_single_area_fills_one_band(example_spec):
    spec = Spec.from_dict(
        {"title": "T", "period": "2021Q1:2021Q4",
         "series": [{"name": "A", "type": "area", "data": [1, 2, 3, 4]}]}
    )
    fig = render(spec)
    assert len(fig.axes[0].collections) == 1  # one fill_between band


def test_area_series_stack():
    spec = Spec.from_dict(
        {"title": "T", "period": "2021Q1:2021Q4",
         "series": [
             {"name": "A", "type": "area", "data": [60, 60, 60, 60]},
             {"name": "B", "type": "area", "data": [30, 30, 30, 30]},
         ]}
    )
    fig = render(spec)
    ax = fig.axes[0]
    assert len(ax.collections) == 2  # two stacked bands
    # stacking: the chart reaches the SUM (~90), not just the tallest layer (60)
    assert ax.get_ylim()[1] >= 88
    assert _legend_texts(fig) == ["A", "B"]


def test_stacked_bars_positive_stack_to_sum():
    spec = Spec.from_dict(
        {"title": "T", "period": "2021Q1:2021Q2",
         "series": [
             {"name": "A", "type": "stacked", "data": [2, 2]},
             {"name": "B", "type": "stacked", "data": [3, 3]},
         ]}
    )
    fig = render(spec)
    ax = fig.axes[0]
    assert len(ax.patches) == 4                # 2 series x 2 periods
    assert ax.get_ylim()[1] >= 4.9             # reaches the SUM (5), not just 3


def test_stacked_bars_negatives_go_below_zero():
    spec = Spec.from_dict(
        {"title": "T", "period": "2021Q1:2021Q2",
         "series": [
             {"name": "A", "type": "stacked", "data": [2, 2]},
             {"name": "B", "type": "stacked", "data": [-1, -1]},
         ]}
    )
    fig = render(spec)
    ax = fig.axes[0]
    lows = [min(p.get_y(), p.get_y() + p.get_height()) for p in ax.patches]
    assert min(lows) <= -0.9                    # a layer stacks downward past 0


def test_bar_series_renders_one_bar_per_point():
    spec = Spec.from_dict(
        {"title": "T", "period": "2021Q1:2021Q4",
         "series": [{"name": "A", "type": "bar", "data": [1, 2, 3, 4]}]}
    )
    fig = render(spec)
    bars = [p for p in fig.axes[0].patches]
    assert len(bars) == 4


def test_two_bar_series_are_grouped_side_by_side():
    spec = Spec.from_dict(
        {"title": "T", "period": "2021Q1:2021Q4",
         "series": [
             {"name": "A", "type": "bar", "data": [1, 2, 3, 4]},
             {"name": "B", "type": "bar", "data": [2, 1, 2, 1]},
         ]}
    )
    fig = render(spec)
    patches = fig.axes[0].patches
    assert len(patches) == 8  # 2 series x 4 periods
    # within the first period the two bars are dodged (different x), each
    # narrower than a full single-series bar, and don't overlap.
    a0, b0 = patches[0], patches[4]
    assert a0.get_x() != b0.get_x()
    assert a0.get_x() + a0.get_width() <= b0.get_x() + 1e-9


def test_save_writes_png_and_infers_backend(example_spec, tmp_path):
    out = tmp_path / "chart.png"
    returned = save(render(example_spec), out)
    assert returned == out
    assert out.exists() and out.stat().st_size > 0


def test_save_rejects_unknown_backend(example_spec, tmp_path):
    with pytest.raises(RenderError):
        save(render(example_spec), tmp_path / "chart.xyz")


# --- vector backends (svg / pdf) ---

@pytest.mark.parametrize("backend", ["png", "svg", "pdf"])
@pytest.mark.parametrize("size", ["slides_half", "slides_full", "word_half", "word_full"])
def test_save_all_backends_and_sizes(example_spec, tmp_path, backend, size):
    """Every backend × named size renders and writes a non-empty file."""
    out = save(render(example_spec, size=size), tmp_path / f"chart.{backend}")
    assert out.exists() and out.stat().st_size > 0


@pytest.mark.parametrize("backend", ["png", "svg"])
def test_background_is_transparent(example_spec, tmp_path, backend):
    """transparent=True: the figure background has alpha=0 for raster (PNG) and
    no background rect for SVG."""
    from PIL import Image
    import numpy as np

    out = save(render(example_spec), tmp_path / f"chart.{backend}")
    if backend == "png":
        arr = np.array(Image.open(out).convert("RGBA"))
        assert arr[0, 0, 3] == 0   # top-left corner is fully transparent
    else:
        svg = out.read_text(encoding="utf-8")
        # matplotlib writes a white rect as the figure background when not
        # transparent; with transparent=True that rect is absent or has opacity 0.
        assert 'opacity:1;fill:#ffffff' not in svg


def test_svg_physical_size_matches_named_preset(example_spec, tmp_path):
    """SVG width/height (in pt) must equal the named size converted from inches at 72 pt/in."""
    import xml.etree.ElementTree as ET
    from econcharts.theme import load_theme

    w_in, h_in = load_theme("bbva").figsize("slides_half")
    out = save(render(example_spec, size="slides_half"), tmp_path / "chart.svg")
    root = ET.parse(out).getroot()
    w_pt = float(root.get("width").rstrip("pt"))
    h_pt = float(root.get("height").rstrip("pt"))
    assert w_pt == pytest.approx(w_in * 72, abs=1)
    assert h_pt == pytest.approx(h_in * 72, abs=1)


def test_svg_title_is_searchable_text(tmp_path):
    """svg.fonttype='none' keeps text as <text> elements — title must be a literal
    string in the file, not encoded as path glyph data."""
    spec = Spec(**{
        "title": "SVG_TITLE_SENTINEL",
        "series": [{"name": "A", "type": "line", "data": [1, 2, 3]}],
        "period": "2024:2026",
    })
    out = save(render(spec), tmp_path / "chart.svg")
    assert "SVG_TITLE_SENTINEL" in out.read_text(encoding="utf-8")


def test_svg_tick_labels_are_searchable_text(tmp_path):
    """svg.fonttype='none' applies to all text, not just the title — tick labels
    must also be literal strings, not paths."""
    spec = Spec(**{
        "title": "T",
        "series": [{"name": "A", "type": "line", "data": [1, 2, 3, 4]}],
        "period": "2024Q1:2024Q4",
    })
    svg = save(render(spec), tmp_path / "chart.svg").read_text(encoding="utf-8")
    # quarterly tick labels default to closing-month format: mar-24, jun-24, …
    assert "mar-24" in svg
    assert "jun-24" in svg


def test_save_pdf_writes_file(example_spec, tmp_path):
    out = save(render(example_spec), tmp_path / "chart.pdf")
    assert out.exists() and out.stat().st_size > 0


# --- visual regression (golden images in tests/baseline/) ---

_SAVEFIG = {"dpi": 150}  # no bbox_inches="tight": exact named size is enforced


@pytest.mark.mpl_image_compare(baseline_dir="baseline", savefig_kwargs=_SAVEFIG, tolerance=20)
def test_image_slides_half(example_spec):
    return render(example_spec, size="slides_half")


@pytest.mark.mpl_image_compare(baseline_dir="baseline", savefig_kwargs=_SAVEFIG, tolerance=20)
def test_image_slides_full(example_spec):
    return render(example_spec, size="slides_full")


@pytest.mark.mpl_image_compare(baseline_dir="baseline", savefig_kwargs=_SAVEFIG, tolerance=20)
def test_image_bar(tmp_path):
    from conftest import EXAMPLES

    return render(Spec.from_yaml(EXAMPLES / "pbi_growth.yaml"), size="slides_full")


@pytest.mark.mpl_image_compare(baseline_dir="baseline", savefig_kwargs=_SAVEFIG, tolerance=20)
def test_image_grouped_bars():
    from conftest import EXAMPLES

    return render(Spec.from_yaml(EXAMPLES / "exportaciones_importaciones.yaml"), size="slides_full")


@pytest.mark.mpl_image_compare(baseline_dir="baseline", savefig_kwargs=_SAVEFIG, tolerance=20)
def test_image_area():
    from conftest import EXAMPLES

    return render(Spec.from_yaml(EXAMPLES / "reservas.yaml"), size="slides_full")


@pytest.mark.mpl_image_compare(baseline_dir="baseline", savefig_kwargs=_SAVEFIG, tolerance=20)
def test_image_stacked_area():
    from conftest import EXAMPLES

    return render(Spec.from_yaml(EXAMPLES / "credito_moneda.yaml"), size="slides_full")


@pytest.mark.mpl_image_compare(baseline_dir="baseline", savefig_kwargs=_SAVEFIG, tolerance=20)
def test_image_stacked_bars():
    from conftest import EXAMPLES

    return render(Spec.from_yaml(EXAMPLES / "contribuciones.yaml"), size="slides_full")


@pytest.mark.mpl_image_compare(baseline_dir="baseline", savefig_kwargs=_SAVEFIG, tolerance=20)
def test_image_secondary_axis():
    from conftest import EXAMPLES

    return render(Spec.from_yaml(EXAMPLES / "reservas_tc.yaml"), size="slides_full")


@pytest.mark.mpl_image_compare(baseline_dir="baseline", savefig_kwargs=_SAVEFIG, tolerance=20)
def test_image_contribution():
    from conftest import EXAMPLES

    return render(Spec.from_yaml(EXAMPLES / "pbi_contribuciones.yaml"), size="slides_full")


@pytest.mark.mpl_image_compare(baseline_dir="baseline", savefig_kwargs=_SAVEFIG, tolerance=20)
def test_image_annotations():
    from conftest import EXAMPLES

    return render(Spec.from_yaml(EXAMPLES / "pbi_growth_anotado.yaml"), size="slides_full")


@pytest.mark.mpl_image_compare(baseline_dir="baseline", savefig_kwargs=_SAVEFIG, tolerance=20)
def test_image_band():
    from conftest import EXAMPLES

    return render(Spec.from_yaml(EXAMPLES / "inflacion_meta.yaml"), size="slides_full")


@pytest.mark.mpl_image_compare(baseline_dir="baseline", savefig_kwargs=_SAVEFIG, tolerance=20)
def test_image_span_on_bars():
    from conftest import EXAMPLES

    return render(Spec.from_yaml(EXAMPLES / "pbi_growth_span.yaml"), size="slides_full")


@pytest.mark.mpl_image_compare(baseline_dir="baseline", savefig_kwargs=_SAVEFIG, tolerance=20)
def test_image_line_marks():
    from conftest import EXAMPLES

    return render(Spec.from_yaml(EXAMPLES / "inflacion_marcada.yaml"), size="slides_full")


@pytest.mark.mpl_image_compare(baseline_dir="baseline", savefig_kwargs=_SAVEFIG, tolerance=20)
def test_image_dense_marks():
    from conftest import EXAMPLES

    return render(Spec.from_yaml(EXAMPLES / "inflacion_densa.yaml"), size="slides_full")


@pytest.mark.mpl_image_compare(baseline_dir="baseline", savefig_kwargs=_SAVEFIG, tolerance=20)
def test_image_three_lines_right_labels():
    from conftest import EXAMPLES

    return render(Spec.from_yaml(EXAMPLES / "tres_series.yaml"), size="slides_full")


@pytest.mark.mpl_image_compare(baseline_dir="baseline", savefig_kwargs=_SAVEFIG, tolerance=20)
def test_image_line_format_overrides():
    from conftest import EXAMPLES

    return render(Spec.from_yaml(EXAMPLES / "formato_lineas.yaml"))


@pytest.mark.mpl_image_compare(baseline_dir="baseline", savefig_kwargs=_SAVEFIG, tolerance=20)
def test_image_wide_frame():
    from conftest import EXAMPLES

    return render(Spec.from_yaml(EXAMPLES / "marco_amplio.yaml"))


@pytest.mark.mpl_image_compare(baseline_dir="baseline", savefig_kwargs=_SAVEFIG, tolerance=20)
def test_image_daily_series():
    from conftest import EXAMPLES

    return render(Spec.from_yaml(EXAMPLES / "tipo_cambio_diario.yaml"), data_root=EXAMPLES)


@pytest.mark.mpl_image_compare(baseline_dir="baseline", savefig_kwargs=_SAVEFIG, tolerance=20)
def test_image_bar_marks():
    from conftest import EXAMPLES

    return render(Spec.from_yaml(EXAMPLES / "pbi_growth_marcado.yaml"), size="slides_full")


@pytest.mark.mpl_image_compare(baseline_dir="baseline", savefig_kwargs=_SAVEFIG, tolerance=20)
def test_image_stacked_marks():
    from conftest import EXAMPLES

    return render(Spec.from_yaml(EXAMPLES / "contribuciones_marcado.yaml"), size="slides_full")


@pytest.mark.mpl_image_compare(baseline_dir="baseline", savefig_kwargs=_SAVEFIG, tolerance=20)
def test_image_area_marks():
    from conftest import EXAMPLES

    return render(Spec.from_yaml(EXAMPLES / "reservas_marcada.yaml"), size="slides_full")


@pytest.mark.mpl_image_compare(baseline_dir="baseline", savefig_kwargs=_SAVEFIG, tolerance=20)
def test_image_no_title():
    from conftest import EXAMPLES

    return render(Spec.from_yaml(EXAMPLES / "pbi_contribuciones_sin_titulo.yaml"), size="slides_full")


def test_highlight_recolors_chosen_bars_and_their_labels():
    from matplotlib.colors import to_hex

    spec = Spec.from_dict({
        "title": "T", "period": "2021:2024",
        "series": [{"name": "A", "type": "bar", "data": [1, 2, 3, 4],
                    "highlight": "last", "mark": "last"}],
    })
    ax = render(spec).axes[0]
    colors = [to_hex(p.get_facecolor()).lower() for p in ax.patches]
    assert colors[:3] == ["#001391"] * 3   # base bars keep the palette primary
    assert colors[3] == "#85c8ff"          # theme default highlight (lightblue)
    # the value label on the highlighted bar matches its bar
    label = [t for t in ax.texts if t.get_text()][-1]
    assert to_hex(label.get_color()).lower() == "#85c8ff"


def test_highlight_named_color_at_token():
    from matplotlib.colors import to_hex

    spec = Spec.from_dict({
        "title": "T", "period": "2021:2024",
        "series": [{"name": "A", "type": "bar", "data": [1, 2, 3, 4],
                    "highlight": {"at": "2022", "color": "orange"}}],
    })
    ax = render(spec).axes[0]
    colors = [to_hex(p.get_facecolor()).lower() for p in ax.patches]
    assert colors == ["#001391", "#ffb56b", "#001391", "#001391"]


def test_unknown_highlight_color_raises_render_error_naming_series():
    spec = Spec.from_dict({
        "title": "T", "period": "2021:2024",
        "series": [{"name": "A", "type": "bar", "data": [1, 2, 3, 4],
                    "highlight": {"at": "last", "color": "chartreuse"}}],
    })
    with pytest.raises(RenderError, match="'A'.*unknown color 'chartreuse'"):
        render(spec)


def _macro_two_lines(**over):
    return Spec.from_dict({
        "title": "T", "period": "2021Q1:2021Q4", "theme": "macro",
        "series": [
            {"name": "A", "type": "line", "data": [1, 2, 3, 4]},
            {"name": "B", "type": "line", "data": [4, 3, 2, 1]},
        ],
        **over,
    })


def test_macro_theme_legend_sits_inside_the_axes():
    fig = render(_macro_two_lines())
    assert not fig.legends                       # no figure-level legend
    assert fig.axes[0].get_legend() is not None  # inside the axes instead


def test_spec_legend_overrides_theme_position():
    fig = render(_macro_two_lines(legend="below"))
    assert fig.legends                           # back to the figure-level row
    assert fig.axes[0].get_legend() is None


def test_unknown_legend_position_raises_render_error():
    with pytest.raises(RenderError, match="legend position 'centered'"):
        render(_macro_two_lines(legend="centered"))

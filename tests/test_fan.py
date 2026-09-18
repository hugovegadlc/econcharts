"""The fan type: a central path plus nested uncertainty intervals.

A fan is one line and N fills, and each fill is between TWO curves. That is the
whole idea, and most of what is worth pinning follows from it: the fills must
not stack, the author's ordering must not matter, and an interval that does not
contain the one inside it is a data mistake no reader could see.
"""
from __future__ import annotations

import matplotlib
import pytest

matplotlib.use("Agg")

from econcharts.render import render, RenderError        # noqa: E402
from econcharts.spec import Spec, SpecError              # noqa: E402
from econcharts import charttypes                        # noqa: E402
from econcharts import theme as theme_mod                # noqa: E402
from econcharts.theme import load_theme                  # noqa: E402

_P = ["2024Q1", "2024Q2", "2024Q3", "2024Q4"]


def _fan(intervals, central=(3.0, 3.0, 3.0, 3.0)):
    return Spec(period=f"{_P[0]}:{_P[-1]}", series=[{
        "name": "I", "type": "fan", "data": dict(zip(_P, central)),
        "intervals": intervals}])


def _iv(conf, lo, hi):
    return {"conf": conf, "lo": dict(zip(_P, [lo] * 4)), "hi": dict(zip(_P, [hi] * 4))}


def _fill_heights(fig):
    """Vertical extent of each fill, in the order they were drawn."""
    out = []
    for coll in fig.axes[0].collections:
        ys = [v[1] for path in coll.get_paths() for v in path.vertices]
        out.append(max(ys) - min(ys))
    return out


def test_a_fan_is_one_line_and_n_fills():
    fig = render(_fan([_iv(90, 2.0, 4.0), _iv(60, 2.5, 3.5)]), size="slides_half")
    assert len(fig.axes[0].collections) == 2, "one fill per interval"
    # one Line2D, PCHIP-smoothed like any other line series
    assert len(fig.axes[0].lines) == 1, "the central path is still an ordinary line"


def test_intervals_are_drawn_widest_first_whatever_the_spec_order():
    """The author declares confidences, not draw order. Given inside-out, the
    fills must still come out outside-in or the wider one hides the rest."""
    fig = render(_fan([_iv(30, 2.9, 3.1), _iv(90, 2.0, 4.0), _iv(60, 2.5, 3.5)]),
                 size="slides_half")
    heights = _fill_heights(fig)
    assert heights == sorted(heights, reverse=True),         f"fills drawn inner-first and would be hidden: {heights}"


def test_an_interval_that_does_not_contain_the_next_is_refused():
    """A 90% band narrower than the 60% one is a mispointed column. Nothing on
    the chart would show it — the narrower fill simply vanishes underneath."""
    with pytest.raises(RenderError, match="does not contain"):
        render(_fan([_iv(90, 2.9, 3.1), _iv(60, 2.0, 4.0)]), size="slides_half")


def test_lo_above_hi_is_refused():
    with pytest.raises(RenderError, match="swapped"):
        render(_fan([_iv(90, 4.0, 2.0)]), size="slides_half")


def test_a_fan_needs_intervals_and_intervals_need_a_fan():
    with pytest.raises(SpecError, match="at least one entry in `intervals`"):
        Spec.from_dict({"series": [{"name": "I", "type": "fan", "data": [1, 2]}]})
    with pytest.raises(SpecError, match="only for fan series"):
        Spec.from_dict({"series": [{"name": "I", "type": "line", "data": [1, 2],
                                    "intervals": [_iv(90, 1, 3)]}]})


def test_conf_is_a_percentage_not_a_fraction():
    """0.9 is a legal 0.9% interval and is almost certainly meant as 90%, so it
    is refused with a message that says which."""
    with pytest.raises(SpecError, match="percentage, not a fraction"):
        Spec.from_dict({"series": [{"name": "I", "type": "fan", "data": [1, 2],
                                    "intervals": [_iv(0.9, 1, 3)]}]})


def test_the_fan_starts_where_its_intervals_do():
    """No forecast-origin concept: leading nulls leave the fills empty over
    history, which is the whole mechanism."""
    spec = Spec(period=f"{_P[0]}:{_P[-1]}", series=[{
        "name": "I", "type": "fan", "data": dict(zip(_P, [3.0] * 4)),
        "intervals": [{"conf": 90,
                       "lo": dict(zip(_P, [None, None, 2.0, 1.5])),
                       "hi": dict(zip(_P, [None, None, 4.0, 4.5]))}]}])
    fig = render(spec, size="slides_half")
    ax = fig.axes[0]
    fill_x = [v[0] for p in ax.collections[0].get_paths() for v in p.vertices]
    central_x = ax.lines[0].get_xdata()
    assert min(fill_x) > min(central_x),         "the fill must not cover the periods whose bounds are null"
    assert max(fill_x) == pytest.approx(max(central_x), rel=1e-6),         "but it must reach the end of the horizon"

def test_the_fills_can_take_a_colour_of_their_own():
    """A fan reads better when the bands recede from the central path rather
    than restating it, so `shade` picks a theme colour NAME for the fills."""
    from econcharts.theme import load_theme
    theme = load_theme("bbva")
    spec = _fan([_iv(90, 2.0, 4.0)])
    spec.series[0].shade = "lightblue"
    fig = render(spec, size="slides_half")
    fill = fig.axes[0].collections[0].get_facecolor()[0][:3]
    want = matplotlib.colors.to_rgb(theme.resolve_color("lightblue"))
    assert fill == pytest.approx(want, abs=1e-6), "the fill ignored `shade`"
    line = matplotlib.colors.to_rgb(fig.axes[0].lines[0].get_color())
    assert line != pytest.approx(want, abs=1e-6), "the central path must keep its own colour"


def test_shade_is_refused_on_anything_but_a_fan():
    with pytest.raises(SpecError, match="only for fan series"):
        Spec.from_dict({"series": [{"name": "I", "type": "line", "data": [1, 2],
                                    "shade": "lightblue"}]})


def test_the_fan_opens_from_the_last_point_without_an_interval():
    """Otherwise the bands begin at full width and the vertical edge reads as a
    step in the data rather than the start of a projection."""
    central = (3.0, 3.0, 3.0, 3.0)
    spec = Spec(period=f"{_P[0]}:{_P[-1]}", series=[{
        "name": "I", "type": "fan", "data": dict(zip(_P, central)),
        "intervals": [{"conf": 90,
                       "lo": dict(zip(_P, [None, None, 2.0, 1.5])),
                       "hi": dict(zip(_P, [None, None, 4.0, 4.5]))}]}])
    fig = render(spec, size="slides_half")
    verts = [v for p in fig.axes[0].collections[0].get_paths() for v in p.vertices]
    x0 = min(v[0] for v in verts)
    at_x0 = [v[1] for v in verts if v[0] == pytest.approx(x0, abs=1e-9)]
    assert max(at_x0) - min(at_x0) == pytest.approx(0.0, abs=1e-9), (
        f"the fan should open from a point on the central path, but starts "
        f"{max(at_x0) - min(at_x0):.3f} wide")


def _composite(fig):
    """Each fill composited over white, in draw order — what the eye actually sees."""
    import numpy as np
    cum, out = np.ones(3), []
    for coll in fig.axes[0].collections:
        rgba = coll.get_facecolor()[0]
        a = coll.get_alpha() if coll.get_alpha() is not None else rgba[3]
        cum = cum * (1 - a) + np.array(rgba[:3]) * a
        out.append(tuple(round(v * 255) for v in cum))
    return out


def test_a_lone_interval_renders_at_the_lightest_step():
    """Not a bug, a consequence: nested fills compound, so the OUTERMOST always
    composites at exactly one alpha and a fan with one interval is all outermost.
    Pinned because it is the surprise that justifies `shade_strength` existing."""
    spec = _fan([_iv(90, 2.0, 4.0)])
    spec.series[0].shade = "lightblue"
    lone = _composite(render(spec, size="slides_half"))
    spec3 = _fan([_iv(90, 2.0, 4.0), _iv(60, 2.5, 3.5), _iv(30, 2.8, 3.2)])
    spec3.series[0].shade = "lightblue"
    ramp = _composite(render(spec3, size="slides_half"))
    assert lone[0] == ramp[0], "a lone interval must match the outermost of a ramp"
    assert ramp[-1][0] < ramp[0][0], "and the ramp must darken inward"


def test_shade_strength_is_a_selection_from_the_theme():
    spec = _fan([_iv(90, 2.0, 4.0)])
    spec.series[0].shade = "lightblue"
    default = _composite(render(spec, size="slides_half"))[0]
    spec.series[0].shade_strength = "strong"
    strong = _composite(render(spec, size="slides_half"))[0]
    assert strong[0] < default[0], f"`strong` must darken the fill: {strong} vs {default}"


def test_an_unknown_strength_names_the_ones_that_exist():
    spec = _fan([_iv(90, 2.0, 4.0)])
    spec.series[0].shade_strength = "extremo"
    with pytest.raises(RenderError, match="soft"):
        render(spec, size="slides_half")


def test_shade_strength_is_refused_on_anything_but_a_fan():
    with pytest.raises(SpecError, match="only for fan series"):
        Spec.from_dict({"series": [{"name": "I", "type": "line", "data": [1, 2],
                                    "shade_strength": "strong"}]})


# --- the visibility floor -----------------------------------------------------
#
# A named strength says how emphatic the house wants a band to look. It cannot
# say whether the band can be seen, because that depends on the colour it is
# drawn in — so these assert the floor, not the alphas.

def test_soft_is_visible_in_every_palette_colour():
    """No colour in the cycle may render `soft` below the visibility floor.

    The bug this forbids is silent: the chart renders, the band is simply not
    there. `grey` at a flat 0.12 composites to delta-E 3.1, under the floor.
    """
    t = load_theme("bbva")
    for name in t.raw["cycle"]:
        color = t.resolve_color(name)
        alpha = charttypes._fan_alpha(t, "soft", color)
        got = theme_mod.delta_e_over_white(color, alpha)
        assert got >= charttypes.MIN_SHADE_DELTA_E - 1e-6, (
            f"{name} composites to delta-E {got:.1f} at alpha {alpha:.3f}")


def test_the_floor_only_ever_raises():
    """It is a floor, not a normalisation — a band already clear of it is left
    alone, so a dark shade keeps the contrast the author asked for."""
    t = load_theme("bbva")
    blue = t.resolve_color("blue")
    assert charttypes._fan_alpha(t, "soft", blue) == 0.12
    for strength in ("soft", "medium", "strong"):
        for name in t.raw["cycle"]:
            table_alpha = charttypes._FAN_STRENGTHS[strength]
            got = charttypes._fan_alpha(t, strength, t.resolve_color(name))
            assert got >= table_alpha


def test_the_example_is_untouched_by_the_floor():
    """`lightblue` at soft sits just above the floor on its own merits.

    Pinned because it is why the floor changed no golden image: if a palette
    edit drops it under, that is a real visual change and should be seen here
    rather than as a silently darker example.
    """
    t = load_theme("bbva")
    assert charttypes._fan_alpha(t, "soft", t.resolve_color("lightblue")) == 0.12


def test_delta_e_over_white_is_zero_for_no_ink():
    t = load_theme("bbva")
    assert theme_mod.delta_e_over_white(t.resolve_color("blue"), 0.0) == pytest.approx(0)
    assert theme_mod.delta_e_over_white("#FFFFFF", 1.0) == pytest.approx(0)
